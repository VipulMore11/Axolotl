"""
Pipeline API Routes
Lists and details GitLab pipelines by proxying via the user's OAuth token.
Enriches with agent engagement data from MongoDB.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

import httpx

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


async def _get_user_gitlab_token(user_id: str) -> tuple[str, str]:
    """Retrieve the user's GitLab access token and base URL from MongoDB."""
    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user_id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="GitLab token not found. Please re-login.")
    base_url = "https://gitlab.com"
    return user_doc["access_token"], base_url


@router.get("")
async def list_pipelines(
    user: UserResponse = Depends(get_current_user),
    per_page: int = 20,
    page: int = 1,
):
    """
    List pipelines from all watched GitLab projects.
    Returns combined results enriched with agent engagement status.
    """
    mongo = get_mongo_service()
    projects = await mongo.get_projects_for_user(user.id)
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    all_pipelines = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for project in projects:
            project_id = project.get("project_id")
            if not project_id:
                continue

            try:
                resp = await client.get(
                    f"{base_url}/api/v4/projects/{project_id}/pipelines",
                    headers={"Authorization": f"Bearer {gitlab_token}"},
                    params={"per_page": per_page, "page": page},
                )
                resp.raise_for_status()
                pipelines = resp.json()

                for pl in pipelines:
                    # Check if agent was engaged for this pipeline
                    events = await mongo.get_events(
                        event_type="pipeline_failed",
                    )
                    agent_engaged = any(
                        e.get("metadata", {}).get("pipeline_id") == str(pl["id"])
                        for e in events
                    )

                    all_pipelines.append({
                        "id": pl["id"],
                        "iid": pl.get("iid"),
                        "project_id": project_id,
                        "project_name": project.get("project_name", f"Project {project_id}"),
                        "ref": pl.get("ref", ""),
                        "sha": pl.get("sha", "")[:7],
                        "status": _map_pipeline_status(pl.get("status", ""), agent_engaged),
                        "source": pl.get("source", ""),
                        "created_at": pl.get("created_at", ""),
                        "updated_at": pl.get("updated_at", ""),
                        "duration": pl.get("duration"),
                        "web_url": pl.get("web_url", ""),
                        "agent_engaged": agent_engaged,
                    })
            except httpx.HTTPStatusError as e:
                print(f"[PIPELINES] Error fetching pipelines for project {project_id}: {e}")
                continue
            except Exception as e:
                print(f"[PIPELINES] Unexpected error for project {project_id}: {e}")
                continue

    # Sort by creation time, newest first
    all_pipelines.sort(key=lambda p: p.get("created_at", ""), reverse=True)

    return {"pipelines": all_pipelines, "total": len(all_pipelines)}


@router.get("/{pipeline_id}")
async def get_pipeline_detail(
    pipeline_id: str,
    project_id: str,
    user: UserResponse = Depends(get_current_user),
):
    """
    Get detail for a single pipeline, including its jobs.
    """
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Fetch pipeline detail
        resp = await client.get(
            f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}",
            headers={"Authorization": f"Bearer {gitlab_token}"},
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        resp.raise_for_status()
        pipeline = resp.json()

        # Fetch jobs
        jobs_resp = await client.get(
            f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/jobs",
            headers={"Authorization": f"Bearer {gitlab_token}"},
            params={"per_page": 100},
        )
        jobs = jobs_resp.json() if jobs_resp.status_code == 200 else []

    return {
        "pipeline": pipeline,
        "jobs": jobs,
    }


def _map_pipeline_status(gitlab_status: str, agent_engaged: bool) -> str:
    """Map GitLab pipeline status to our frontend status type."""
    if gitlab_status == "failed" and agent_engaged:
        return "fixing"
    status_map = {
        "running": "running",
        "pending": "running",
        "success": "passed",
        "failed": "failed",
        "canceled": "failed",
        "skipped": "passed",
        "manual": "running",
        "created": "running",
    }
    return status_map.get(gitlab_status, gitlab_status)
