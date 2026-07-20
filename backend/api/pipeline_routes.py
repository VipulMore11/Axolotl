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


async def _get_user_token(user_id: str) -> tuple[str, str]:
    """Retrieve the user's access token and provider from MongoDB."""
    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user_id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="Access token not found. Please re-login.")
    provider = user_doc.get("provider", "gitlab")
    return user_doc["access_token"], provider


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
    user_doc = await mongo.get_user_by_id(user.id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="Access token not found. Please re-login.")
    token = user_doc["access_token"]

    all_pipelines = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for project in projects:
            project_id = project.get("project_id")
            if not project_id:
                continue

            provider = project.get("provider", "gitlab")

            try:
                if provider == "bitbucket":
                    # Bitbucket Cloud API
                    workspace = project.get("workspace", "")
                    repo_slug = project.get("repo_slug", "")
                    if not workspace or not repo_slug:
                        # Try to extract from project_id (format: workspace/repo_slug)
                        if "/" in project_id:
                            workspace, repo_slug = project_id.split("/", 1)
                        else:
                            continue

                    resp = await client.get(
                        f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pipelines/",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"pagelen": per_page, "page": page, "sort": "-created_on"},
                    )
                    resp.raise_for_status()
                    pipelines = resp.json().get("values", [])

                    for pl in pipelines:
                        state = pl.get("state", {})
                        result_obj = state.get("result", {})
                        bb_status = result_obj.get("name", state.get("name", "unknown")).lower()

                        # Check if agent was engaged
                        events = await mongo.get_events(event_type="pipeline_failed")
                        pipeline_uuid = pl.get("uuid", "").strip("{}")
                        agent_engaged = any(
                            e.get("metadata", {}).get("pipeline_id") == pipeline_uuid
                            for e in events
                        )

                        duration_seconds = pl.get("duration_in_seconds")
                        target = pl.get("target", {})

                        all_pipelines.append({
                            "id": pipeline_uuid,
                            "iid": pl.get("build_number"),
                            "project_id": project_id,
                            "project_name": project.get("project_name", f"Project {project_id}"),
                            "ref": target.get("ref_name", ""),
                            "sha": target.get("commit", {}).get("hash", "")[:7],
                            "status": _map_pipeline_status(bb_status, agent_engaged),
                            "source": pl.get("trigger", {}).get("name", ""),
                            "created_at": pl.get("created_on", ""),
                            "updated_at": pl.get("completed_on", pl.get("created_on", "")),
                            "duration": duration_seconds,
                            "web_url": f"https://bitbucket.org/{workspace}/{repo_slug}/addon/pipelines/home#!/results/{pipeline_uuid}",
                            "agent_engaged": agent_engaged,
                            "provider": "bitbucket",
                        })
                else:
                    # GitLab API
                    base_url = "https://gitlab.com"
                    resp = await client.get(
                        f"{base_url}/api/v4/projects/{project_id}/pipelines",
                        headers={"Authorization": f"Bearer {token}"},
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
                            "provider": "gitlab",
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
    token, _ = await _get_user_token(user.id)

    # Determine provider from project config
    mongo = get_mongo_service()
    project_config = await mongo.get_project_by_id(project_id)
    provider = project_config.get("provider", "gitlab") if project_config else "gitlab"

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "bitbucket":
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if not workspace or not repo_slug:
                if "/" in project_id:
                    workspace, repo_slug = project_id.split("/", 1)

            # Fetch pipeline detail
            resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pipelines/{{{pipeline_id}}}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Pipeline not found")
            resp.raise_for_status()
            pipeline = resp.json()

            # Fetch steps (equivalent to jobs)
            steps_resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pipelines/{{{pipeline_id}}}/steps/",
                headers={"Authorization": f"Bearer {token}"},
                params={"pagelen": 100},
            )
            jobs = steps_resp.json().get("values", []) if steps_resp.status_code == 200 else []
        else:
            base_url = "https://gitlab.com"
            # Fetch pipeline detail
            resp = await client.get(
                f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Pipeline not found")
            resp.raise_for_status()
            pipeline = resp.json()

            # Fetch jobs
            jobs_resp = await client.get(
                f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/jobs",
                headers={"Authorization": f"Bearer {token}"},
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
