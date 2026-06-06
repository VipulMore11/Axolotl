"""
Webhook Routes
FastAPI routes for handling GitLab webhook events.
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import hmac
import hashlib

from db.mongo_service import get_mongo_service


# Pydantic models for request validation
class PipelineEvent(BaseModel):
    object_kind: str
    event_name: str
    project_id: int
    pipeline_id: int
    status: str
    branch: str
    commit_sha: Optional[str] = None


# Initialize FastAPI app
app = FastAPI(title="Axolotl Webhook Server")

# Store for webhook processing
WEBHOOK_SECRET = "axolotl-webhook-secret"  # TODO: Move to environment variable


def verify_gitlab_webhook(request_body: bytes, token: str, signature: str) -> bool:
    """
    Verify GitLab webhook signature.
    
    Args:
        request_body: Raw request body
        token: Webhook token
        signature: X-Gitlab-Token header value
    
    Returns:
        True if signature is valid
    """
    return signature == token


@app.post("/webhooks/gitlab/pipeline")
async def handle_pipeline_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle GitLab pipeline webhook events.
    
    This endpoint receives pipeline failure notifications and triggers the agent workflow.
    """
    try:
        # Get raw body for signature verification
        body = await request.body()
        
        # Get headers
        headers = request.headers
        token = headers.get("X-Gitlab-Token", "")
        
        # Verify signature (optional for now, can be enabled with proper config)
        # if not verify_gitlab_webhook(body, WEBHOOK_SECRET, token):
        #     raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Parse JSON payload
        payload = json.loads(body)
        
        # Filter for pipeline events
        if payload.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "not a pipeline event"}
        
        # Filter for failed pipelines
        if payload.get("status") != "failed":
            return {"status": "ignored", "reason": "pipeline did not fail"}
        
        # Extract relevant information
        project_id = str(payload.get("project_id"))
        pipeline_id = str(payload.get("id"))
        branch = payload.get("ref")
        commit_sha = payload.get("sha")
        
        print(f"Pipeline failure detected: Project {project_id}, Pipeline {pipeline_id}, Branch {branch}")
        
        # Verify project exists in MongoDB
        mongo_service = get_mongo_service()
        project_config = await mongo_service.get_project_by_id(project_id)
        
        if not project_config:
            print(f"Project {project_id} not found in MongoDB")
            return {
                "status": "error",
                "reason": f"Project {project_id} not configured in system"
            }
        
        # Queue the agent workflow as a background task
        background_tasks.add_task(
            process_pipeline_failure,
            project_id,
            pipeline_id,
            branch,
            commit_sha
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


@app.post("/webhooks/gitlab/push")
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"name": "Axolotl Webhook Server", "version": "1.0.0"}


async def process_pipeline_failure(
    project_id: str,
    pipeline_id: str,
    branch: str,
    commit_sha: Optional[str]
):
    """
    Process pipeline failure in the background.
    
    This function is called when a pipeline failure is detected.
    It would be called by the Orchestrator (Person 1) to trigger the agent.
    
    Args:
        project_id: GitLab project ID
        pipeline_id: GitLab pipeline ID
        branch: Branch that failed
        commit_sha: Commit SHA
    """
    print(f"Processing pipeline failure: Project {project_id}, Pipeline {pipeline_id}")
    
    # TODO: This is where the Orchestrator would be triggered
    # The orchestrator would:
    # 1. Call get_pipeline_logs via the MCP client
    # 2. Analyze logs using Gemini
    # 3. Generate a fix proposal
    # 4. Call create_branch, update_file, create_merge_request via MCP
    # 5. Publish events to the frontend via WebSocket
    
    print(f"Pipeline failure processing initiated for {project_id}/{pipeline_id}")
