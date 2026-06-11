"""
Merge Request API Routes
Lists merge requests from GitLab, with approve/reject actions.
"""

from fastapi import APIRouter, Depends, HTTPException

import httpx

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/merge-requests", tags=["merge-requests"])


async def _get_user_gitlab_token(user_id: str) -> tuple[str, str]:
    """Retrieve the user's GitLab access token and base URL."""
    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user_id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="GitLab token not found.")
    return user_doc["access_token"], "https://gitlab.com"


@router.get("")
async def list_merge_requests(
    user: UserResponse = Depends(get_current_user),
    state: str = "all",
    per_page: int = 20,
    page: int = 1,
):
    """
    List merge requests from all watched projects.
    """
    mongo = get_mongo_service()
    projects = await mongo.get_projects_for_user(user.id)
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    all_mrs = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for project in projects:
            project_id = project.get("project_id")
            if not project_id:
                continue

            try:
                resp = await client.get(
                    f"{base_url}/api/v4/projects/{project_id}/merge_requests",
                    headers={"Authorization": f"Bearer {gitlab_token}"},
                    params={
                        "state": state if state != "all" else "all",
                        "per_page": per_page,
                        "page": page,
                        "order_by": "updated_at",
                        "sort": "desc",
                    },
                )
                resp.raise_for_status()
                mrs = resp.json()

                for mr in mrs:
                    author = mr.get("author", {})
                    author_name = author.get("name", "Unknown")
                    author_username = author.get("username", "")
                    is_agent = "axolotl" in author_username.lower() or "axolotl" in author_name.lower()

                    # Map GitLab MR state to our frontend type
                    mr_status = mr.get("state", "opened")
                    if mr_status == "opened":
                        mr_status = "open"

                    diff_stats = mr.get("diff_stats", {}) or {}

                    pipeline_info = mr.get("head_pipeline") or {}
                    pipeline_passing = pipeline_info.get("status") == "success" if pipeline_info else False

                    all_mrs.append({
                        "iid": f"!{mr['iid']}",
                        "raw_iid": mr["iid"],
                        "title": mr.get("title", ""),
                        "project": project.get("project_name", f"Project {project_id}"),
                        "project_id": project_id,
                        "source_branch": mr.get("source_branch", ""),
                        "target_branch": mr.get("target_branch", ""),
                        "author": author_name,
                        "author_username": author_username,
                        "author_is_agent": is_agent,
                        "author_avatar_url": author.get("avatar_url", ""),
                        "status": mr_status,
                        "additions": diff_stats.get("additions", 0),
                        "deletions": diff_stats.get("deletions", 0),
                        "files_changed": mr.get("changes_count", 0),
                        "approvals_required": mr.get("approvals_required", 0),
                        "approvals_given": mr.get("approvals_left", 0),
                        "pipeline_passing": pipeline_passing,
                        "opened_at": mr.get("created_at", ""),
                        "web_url": mr.get("web_url", ""),
                        "description": mr.get("description", ""),
                        "root_cause": _extract_root_cause(mr.get("description", "")),
                    })
            except httpx.HTTPStatusError as e:
                print(f"[MR] Error fetching MRs for project {project_id}: {e}")
                continue
            except Exception as e:
                print(f"[MR] Unexpected error for project {project_id}: {e}")
                continue

    return {"merge_requests": all_mrs, "total": len(all_mrs)}


@router.get("/{project_id}/{mr_iid}")
async def get_merge_request_detail(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Get a single merge request with its diff."""
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # MR detail
        resp = await client.get(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
            headers={"Authorization": f"Bearer {gitlab_token}"},
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        resp.raise_for_status()
        mr = resp.json()

        # MR changes (diff)
        changes_resp = await client.get(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes",
            headers={"Authorization": f"Bearer {gitlab_token}"},
        )
        changes = changes_resp.json().get("changes", []) if changes_resp.status_code == 200 else []

    return {"merge_request": mr, "changes": changes}


@router.post("/{project_id}/{mr_iid}/approve")
async def approve_merge_request(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Approve a merge request via GitLab API."""
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/approve",
            headers={"Authorization": f"Bearer {gitlab_token}"},
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=403, detail="Not authorized to approve")
        resp.raise_for_status()

    return {"status": "approved", "mr_iid": mr_iid}


@router.post("/{project_id}/{mr_iid}/merge")
async def merge_merge_request(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Merge a merge request via GitLab API."""
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/merge",
            headers={"Authorization": f"Bearer {gitlab_token}"},
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        if resp.status_code == 405:
            raise HTTPException(status_code=405, detail="Merge request cannot be merged")
        resp.raise_for_status()

    return {"status": "merged", "mr_iid": mr_iid}


@router.post("/{project_id}/{mr_iid}/reject")
async def reject_merge_request(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Close/reject a merge request via GitLab API."""
    gitlab_token, base_url = await _get_user_gitlab_token(user.id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
            headers={"Authorization": f"Bearer {gitlab_token}"},
            json={"state_event": "close"},
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        resp.raise_for_status()

    return {"status": "rejected", "mr_iid": mr_iid}


def _extract_root_cause(description: str) -> str:
    """Extract root cause from Axolotl's MR description format."""
    if not description:
        return "—"
    for line in description.split("\n"):
        if "**Root Cause:**" in line:
            return line.replace("**Root Cause:**", "").strip()
    return "—"
