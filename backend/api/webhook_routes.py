"""
Webhook Routes
FastAPI routes for handling GitLab webhook events.
Receives pipeline failure notifications and triggers the agent workflow.
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from typing import Optional
import json
import time

from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# ── Circuit-breaker state ────────────────────────────────────────────
# Tracks pipeline IDs that have already been processed (or are in-flight)
# and per-project cooldowns to prevent infinite loops.

_processed_pipelines: set[str] = set()          # pipeline IDs we've already seen
_project_cooldowns: dict[str, float] = {}       # project_id → timestamp of last run
PROJECT_COOLDOWN_SECONDS = 60                   # minimum gap between runs per project
MAX_PROCESSED_CACHE = 500                       # prevent unbounded memory growth

@router.post("/gitlab/test")
async def handle_test_webhook(
    request: Request
):
    payload = await request.json()

    print("=" * 100)
    print(payload)
    print("=" * 100)

    return {"status": "received"}

@router.post("/gitlab/pipeline")
async def handle_pipeline_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle GitLab pipeline webhook events.

    This endpoint receives pipeline failure notifications and triggers the agent workflow
    via the orchestrator.

    Circuit-breaker guards:
      1. Ignore non-pipeline events
      2. Ignore pipelines that did NOT fail
      3. Ignore failures on axolotl/* branches (our own fix branches)
      4. Ignore duplicate pipeline IDs (already processed or in-flight)
      5. Enforce a per-project cooldown to prevent rapid-fire loops
    """
    try:
        # Get raw body
        body = await request.body()

        # Parse JSON payload
        payload = json.loads(body)

        # Guard 1: Only pipeline events
        if payload.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "not a pipeline event"}

        object_attributes = payload.get("object_attributes", {})
        status = object_attributes.get("status")

        # Guard 2: Only failed pipelines
        if status != "failed":
            return {"status": "ignored", "reason": "pipeline did not fail"}

        project = payload.get("project", {})
        project_id = str(project.get("id"))
        pipeline_id = str(object_attributes.get("id"))
        branch = object_attributes.get("ref")
        commit_sha = object_attributes.get("sha")

        print(f"[WEBHOOK] Pipeline failure detected: Project {project_id}, Pipeline {pipeline_id}, Branch {branch}")

        # ── Guard 3: Skip failures on Axolotl's own fix branches ─────
        if branch and branch.startswith("axolotl/"):
            print(f"[WEBHOOK] SKIPPED — failure is on Axolotl fix branch '{branch}', ignoring to prevent loop")
            return {
                "status": "ignored",
                "reason": f"Pipeline failed on Axolotl fix branch '{branch}' — not re-processing",
            }

        # ── Guard 4: Deduplicate — skip if this pipeline was already handled ──
        if pipeline_id in _processed_pipelines:
            print(f"[WEBHOOK] SKIPPED — pipeline {pipeline_id} already processed")
            return {
                "status": "ignored",
                "reason": f"Pipeline {pipeline_id} already processed or in-flight",
            }

        # ── Guard 5: Per-project cooldown ─────────────────────────────
        now = time.time()
        last_run = _project_cooldowns.get(project_id, 0)
        if now - last_run < PROJECT_COOLDOWN_SECONDS:
            remaining = int(PROJECT_COOLDOWN_SECONDS - (now - last_run))
            print(f"[WEBHOOK] SKIPPED — project {project_id} is in cooldown ({remaining}s remaining)")
            return {
                "status": "ignored",
                "reason": f"Project {project_id} in cooldown — {remaining}s remaining before next run",
            }

        # ── Mark as in-flight ─────────────────────────────────────────
        _processed_pipelines.add(pipeline_id)
        _project_cooldowns[project_id] = now

        # Prevent unbounded memory growth
        if len(_processed_pipelines) > MAX_PROCESSED_CACHE:
            # Remove oldest entries (set doesn't preserve order, just trim)
            excess = len(_processed_pipelines) - MAX_PROCESSED_CACHE
            for _ in range(excess):
                _processed_pipelines.pop()

        session_id = pipeline_id

        # Verify project exists in MongoDB
        mongo_service = get_mongo_service()
        project_config = await mongo_service.get_project_by_id(project_id)

        # ── Debug: compare webhook data vs MongoDB ──
        print(
            f"[DEBUG] Webhook vs MongoDB comparison:\n"
            f"  webhook project_id  = '{project_id}' (type={type(project_id).__name__})\n"
            f"  MongoDB project_id  = '{project_config.get('project_id', 'N/A')}' (type={type(project_config.get('project_id')).__name__})" if project_config else
            f"[DEBUG] Webhook project_id = '{project_id}' — NOT FOUND in MongoDB"
        )
        if project_config:
            token = project_config.get("access_token", "")
            token_preview = f"{token[:10]}...{token[-4:]}" if len(token) > 14 else "***"
            print(
                f"  gitlab_url          = {project_config.get('gitlab_url')}\n"
                f"  access_token        = {token_preview}\n"
                f"  project_name        = {project_config.get('project_name', 'N/A')}"
            )

        if not project_config:
            print(f"Project {project_id} not found in MongoDB")
            _processed_pipelines.discard(pipeline_id)  # allow retry since we didn't actually run
            return {
                "status": "error",
                "reason": f"Project {project_id} not configured in system"
            }

        # Queue the agent workflow as a background task
        background_tasks.add_task(
            process_pipeline_failure,
            project_id,
            pipeline_id,
            session_id,
            branch,
            commit_sha,
            project_config.get("user_id")
        )

        return {
            "status": "received",
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "message": "Pipeline failure received, agent will analyze and create fix"
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"Error handling webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gitlab/push")
async def handle_push_webhook(request: Request):
    """
    Handle GitLab push webhook events (for monitoring/logging purposes).
    """
    try:
        body = await request.body()
        payload = json.loads(body)

        project_id = payload.get("project_id")
        branch = payload.get("ref")

        print(f"Push event received: Project {project_id}, Branch {branch}")

        return {"status": "received"}

    except Exception as e:
        print(f"Error handling push webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_pipeline_failure(
    project_id: str,
    pipeline_id: str,
    session_id: str,
    branch: str,
    commit_sha: Optional[str],
    user_id: Optional[str] = None
):
    """
    Process pipeline failure in the background.
    Uses the PipelineOrchestrator to run the full fix workflow via MCP tools.

    Args:
        project_id: GitLab project ID
        pipeline_id: GitLab pipeline ID
        branch: Branch that failed
        commit_sha: Commit SHA
        user_id: The owner of the project
    """
    print(f"Processing pipeline failure: Project {project_id}, Pipeline {pipeline_id}")

    try:
        # Import here to avoid circular imports at module level
        from core.dependencies import get_orchestrator

        orchestrator = get_orchestrator()
        result = await orchestrator.handle_pipeline_failure(
            project_id=project_id,
            pipeline_id=pipeline_id,
            branch=branch,
            user_id=user_id,
        )
        print(f"Pipeline fix workflow completed: {result}")

    except Exception as e:
        print(f"Error in pipeline fix workflow: {e}")
        import traceback
        traceback.print_exc()
