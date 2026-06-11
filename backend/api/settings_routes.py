"""
Settings API Routes
CRUD for watched projects, agent configuration, and GitLab repo browsing.
Auto-registers webhooks when a project is connected.
"""

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

import httpx

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── Pydantic models ─────────────────────────────────────────────────

class AddProjectRequest(BaseModel):
    project_id: str
    gitlab_url: str = "https://gitlab.com"
    auto_fix: bool = True


class UpdateProjectRequest(BaseModel):
    auto_fix: Optional[bool] = None


class AgentSettingsRequest(BaseModel):
    confidence_threshold: Optional[int] = None
    require_approval: Optional[bool] = None
    auto_branch: Optional[bool] = None
    notify_failures: Optional[bool] = None


# ── GitLab Repos (Browse user's repositories) ──────────────────────

@router.get("/gitlab-repos")
async def list_gitlab_repos(
    user: UserResponse = Depends(get_current_user),
    search: str = "",
    per_page: int = 20,
    page: int = 1,
):
    """
    List GitLab repositories the user has access to.
    Returns repos with key metadata for the project selector UI.
    """
    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user.id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="GitLab token not found. Please re-login.")

    gitlab_token = user_doc["access_token"]
    base_url = "https://gitlab.com"

    params = {
        "membership": "true",
        "per_page": per_page,
        "page": page,
        "order_by": "last_activity_at",
        "sort": "desc",
        "min_access_level": 30,  # Developer access or higher
    }
    if search:
        params["search"] = search

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base_url}/api/v4/projects",
                headers={"Authorization": f"Bearer {gitlab_token}"},
                params=params,
            )
            resp.raise_for_status()
            projects = resp.json()
    except httpx.HTTPStatusError as e:
        print(f"[SETTINGS] GitLab API error: {e}")
        raise HTTPException(status_code=502, detail=f"GitLab API error: {e.response.status_code}")
    except Exception as e:
        print(f"[SETTINGS] Error fetching repos: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch repositories from GitLab")

    # Get list of already-watched project IDs
    watched = await mongo.get_projects_for_user(user.id)
    watched_ids = {str(p.get("project_id")) for p in watched}

    repos = []
    for p in projects:
        repos.append({
            "id": p["id"],
            "name": p.get("name", ""),
            "path_with_namespace": p.get("path_with_namespace", ""),
            "description": p.get("description") or "",
            "web_url": p.get("web_url", ""),
            "default_branch": p.get("default_branch", "main"),
            "avatar_url": p.get("avatar_url"),
            "last_activity_at": p.get("last_activity_at", ""),
            "visibility": p.get("visibility", ""),
            "star_count": p.get("star_count", 0),
            "forks_count": p.get("forks_count", 0),
            "already_connected": str(p["id"]) in watched_ids,
        })

    return {"repos": repos, "total": len(repos)}


# ── Projects ────────────────────────────────────────────────────────

@router.get("/projects")
async def list_watched_projects(
    user: UserResponse = Depends(get_current_user),
):
    """List all watched projects for the current user."""
    mongo = get_mongo_service()
    projects = await mongo.get_projects_for_user(user.id)

    result = []
    for p in projects:
        result.append({
            "project_id": p.get("project_id"),
            "project_name": p.get("project_name", f"Project {p.get('project_id')}"),
            "gitlab_url": p.get("gitlab_url", "https://gitlab.com"),
            "branch": p.get("branch", "main"),
            "auto_fix": p.get("auto_fix", True),
            "webhook_registered": p.get("webhook_registered", False),
            "webhook_id": p.get("webhook_id"),
        })

    return {"projects": result}


@router.post("/projects")
async def add_watched_project(
    body: AddProjectRequest,
    user: UserResponse = Depends(get_current_user),
):
    """
    Connect a GitLab project to Axolotl.
    Steps:
      1. Fetch project metadata from GitLab
      2. Register a pipeline webhook on the project
      3. Save to MongoDB
    """
    mongo = get_mongo_service()

    # Check if already exists
    existing = await mongo.get_project_by_id(body.project_id)
    if existing:
        await mongo.link_project_to_user(body.project_id, user.id)
        return {"status": "already_exists", "project_id": body.project_id}

    # Get user's GitLab token
    user_doc = await mongo.get_user_by_id(user.id)
    gitlab_token = user_doc.get("access_token", "") if user_doc else ""
    if not gitlab_token:
        raise HTTPException(status_code=401, detail="GitLab token not found.")

    project_name = f"Project {body.project_id}"
    default_branch = "main"

    # Step 1: Fetch project metadata from GitLab
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{body.gitlab_url}/api/v4/projects/{body.project_id}",
                headers={"Authorization": f"Bearer {gitlab_token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                project_name = data.get("path_with_namespace", project_name)
                default_branch = data.get("default_branch", "main")
            else:
                print(f"[SETTINGS] Failed to fetch project {body.project_id}: {resp.status_code}")
    except Exception as e:
        print(f"[SETTINGS] Error fetching project info: {e}")

    # Step 2: Register webhook on the GitLab project
    webhook_id = None
    webhook_registered = False
    webhook_url = _get_webhook_url()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # First check if webhook already exists
            existing_hooks = await client.get(
                f"{body.gitlab_url}/api/v4/projects/{body.project_id}/hooks",
                headers={"Authorization": f"Bearer {gitlab_token}"},
            )
            if existing_hooks.status_code == 200:
                for hook in existing_hooks.json():
                    if hook.get("url") == webhook_url:
                        webhook_id = hook["id"]
                        webhook_registered = True
                        print(f"[SETTINGS] Webhook already exists for project {body.project_id}: hook #{webhook_id}")
                        break

            if not webhook_registered:
                # Create new webhook
                webhook_secret = os.getenv("WEBHOOK_SECRET", "axolotl-webhook-secret")
                hook_resp = await client.post(
                    f"{body.gitlab_url}/api/v4/projects/{body.project_id}/hooks",
                    headers={"Authorization": f"Bearer {gitlab_token}"},
                    json={
                        "url": webhook_url,
                        "push_events": False,
                        "pipeline_events": True,
                        "merge_requests_events": True,
                        "enable_ssl_verification": True,
                        "token": webhook_secret,
                    },
                )
                if hook_resp.status_code in (200, 201):
                    hook_data = hook_resp.json()
                    webhook_id = hook_data.get("id")
                    webhook_registered = True
                    print(f"[SETTINGS] Webhook registered for project {body.project_id}: hook #{webhook_id}")
                else:
                    error_msg = hook_resp.text
                    print(f"[SETTINGS] Failed to register webhook: {hook_resp.status_code} — {error_msg}")
    except Exception as e:
        print(f"[SETTINGS] Error registering webhook: {e}")

    # Step 3: Save to MongoDB
    project_data = {
        "project_id": body.project_id,
        "project_name": project_name,
        "gitlab_url": body.gitlab_url,
        "access_token": gitlab_token,
        "auto_fix": body.auto_fix,
        "user_id": user.id,
        "branch": default_branch,
        "webhook_registered": webhook_registered,
        "webhook_id": webhook_id,
    }

    doc_id = await mongo.add_project(project_data)
    return {
        "status": "created",
        "project_id": body.project_id,
        "id": doc_id,
        "webhook_registered": webhook_registered,
        "webhook_id": webhook_id,
    }


@router.put("/projects/{project_id}")
async def update_watched_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: UserResponse = Depends(get_current_user),
):
    """Update a watched project's settings (e.g. auto-fix toggle)."""
    mongo = get_mongo_service()
    update_data = {}
    if body.auto_fix is not None:
        update_data["auto_fix"] = body.auto_fix

    if not update_data:
        return {"status": "no_changes"}

    success = await mongo.update_project(project_id, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "updated", "project_id": project_id}


@router.delete("/projects/{project_id}")
async def delete_watched_project(
    project_id: str,
    user: UserResponse = Depends(get_current_user),
):
    """Remove a watched project and unregister its webhook."""
    mongo = get_mongo_service()

    # Get project to find webhook_id
    project = await mongo.get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Unregister webhook from GitLab
    webhook_id = project.get("webhook_id")
    if webhook_id:
        user_doc = await mongo.get_user_by_id(user.id)
        gitlab_token = user_doc.get("access_token", "") if user_doc else ""
        gitlab_url = project.get("gitlab_url", "https://gitlab.com")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(
                    f"{gitlab_url}/api/v4/projects/{project_id}/hooks/{webhook_id}",
                    headers={"Authorization": f"Bearer {gitlab_token}"},
                )
                if resp.status_code in (200, 204):
                    print(f"[SETTINGS] Webhook #{webhook_id} removed from project {project_id}")
                else:
                    print(f"[SETTINGS] Failed to remove webhook: {resp.status_code}")
        except Exception as e:
            print(f"[SETTINGS] Error removing webhook: {e}")

    success = await mongo.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


# ── Agent Settings ──────────────────────────────────────────────────

@router.get("/agent")
async def get_agent_settings(
    user: UserResponse = Depends(get_current_user),
):
    """Get agent configuration for the current user."""
    mongo = get_mongo_service()
    settings = await mongo.get_user_settings(user.id)
    return {"settings": settings}


@router.put("/agent")
async def update_agent_settings(
    body: AgentSettingsRequest,
    user: UserResponse = Depends(get_current_user),
):
    """Update agent configuration."""
    mongo = get_mongo_service()
    current = await mongo.get_user_settings(user.id)

    if body.confidence_threshold is not None:
        current["confidence_threshold"] = body.confidence_threshold
    if body.require_approval is not None:
        current["require_approval"] = body.require_approval
    if body.auto_branch is not None:
        current["auto_branch"] = body.auto_branch
    if body.notify_failures is not None:
        current["notify_failures"] = body.notify_failures

    await mongo.update_user_settings(user.id, current)
    return {"status": "updated", "settings": current}


# ── Helpers ─────────────────────────────────────────────────────────

def _get_webhook_url() -> str:
    """
    Build the webhook URL Axolotl registers on GitLab projects.
    Uses GITLAB_REDIRECT_URI to detect the public ngrok/production base URL,
    since that's the same tunnel the OAuth callback uses.
    """
    redirect_uri = os.getenv("GITLAB_REDIRECT_URI", "")
    if redirect_uri:
        # Extract base URL from redirect URI (e.g. https://xxx.ngrok-free.dev/auth/gitlab/callback → https://xxx.ngrok-free.dev)
        from urllib.parse import urlparse
        parsed = urlparse(redirect_uri)
        base = f"{parsed.scheme}://{parsed.netloc}"
        return f"{base}/webhooks/gitlab/pipeline"

    # Fallback
    host = os.getenv("WEBHOOK_SERVER_HOST", "0.0.0.0")
    port = os.getenv("WEBHOOK_SERVER_PORT", "8000")
    return f"http://{host}:{port}/webhooks/gitlab/pipeline"
