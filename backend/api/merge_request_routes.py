"""
Merge Request / Pull Request API Routes
Lists merge requests (GitLab) and pull requests (Bitbucket) from watched projects,
with approve/reject/merge actions.
"""

from fastapi import APIRouter, Depends, HTTPException

import httpx

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/merge-requests", tags=["merge-requests"])


async def _get_user_token(user_id: str) -> str:
    """Retrieve the user's access token from MongoDB."""
    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user_id)
    if not user_doc or not user_doc.get("access_token"):
        raise HTTPException(status_code=401, detail="Access token not found.")
    return user_doc["access_token"]


async def _get_project_provider(project_id: str) -> tuple[dict, str]:
    """Get project config and its provider."""
    mongo = get_mongo_service()
    project_config = await mongo.get_project_by_id(project_id)
    provider = project_config.get("provider", "gitlab") if project_config else "gitlab"
    return project_config or {}, provider


@router.get("")
async def list_merge_requests(
    user: UserResponse = Depends(get_current_user),
    state: str = "all",
    per_page: int = 20,
    page: int = 1,
):
    """
    List merge requests / pull requests from all watched projects.
    """
    mongo = get_mongo_service()
    projects = await mongo.get_projects_for_user(user.id)
    token = await _get_user_token(user.id)

    all_mrs = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for project in projects:
            project_id = project.get("project_id")
            if not project_id:
                continue

            provider = project.get("provider", "gitlab")

            try:
                if provider == "bitbucket":
                    # ── Bitbucket Pull Requests ──
                    workspace = project.get("workspace", "")
                    repo_slug = project.get("repo_slug", "")
                    if not workspace or not repo_slug:
                        if "/" in project_id:
                            workspace, repo_slug = project_id.split("/", 1)
                        else:
                            continue

                    # Map state filter
                    bb_state = ""
                    if state == "open":
                        bb_state = "OPEN"
                    elif state == "merged":
                        bb_state = "MERGED"
                    elif state == "closed":
                        bb_state = "DECLINED"
                    # "all" = no state filter

                    params = {
                        "pagelen": per_page,
                        "page": page,
                        "sort": "-updated_on",
                    }
                    if bb_state:
                        params["state"] = bb_state

                    resp = await client.get(
                        f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests",
                        headers={"Authorization": f"Bearer {token}"},
                        params=params,
                    )
                    resp.raise_for_status()
                    prs = resp.json().get("values", [])

                    for pr in prs:
                        author = pr.get("author", {})
                        author_name = author.get("display_name", "Unknown")
                        author_username = author.get("nickname", author.get("username", ""))
                        is_agent = "axolotl" in author_username.lower() or "axolotl" in author_name.lower()

                        pr_state = pr.get("state", "OPEN").lower()
                        if pr_state == "open":
                            status = "open"
                        elif pr_state == "merged":
                            status = "merged"
                        else:
                            status = "closed"

                        avatar_url = author.get("links", {}).get("avatar", {}).get("href", "")
                        pr_url = pr.get("links", {}).get("html", {}).get("href", "")

                        all_mrs.append({
                            "iid": f"#{pr['id']}",
                            "raw_iid": pr["id"],
                            "title": pr.get("title", ""),
                            "project": project.get("project_name", f"Project {project_id}"),
                            "project_id": project_id,
                            "source_branch": pr.get("source", {}).get("branch", {}).get("name", ""),
                            "target_branch": pr.get("destination", {}).get("branch", {}).get("name", ""),
                            "author": author_name,
                            "author_username": author_username,
                            "author_is_agent": is_agent,
                            "author_avatar_url": avatar_url,
                            "status": status,
                            "additions": 0,  # Bitbucket doesn't include diff stats in PR list
                            "deletions": 0,
                            "files_changed": 0,
                            "approvals_required": 0,
                            "approvals_given": len(pr.get("participants", [p for p in pr.get("participants", []) if p.get("approved")])),
                            "pipeline_passing": False,
                            "opened_at": pr.get("created_on", ""),
                            "web_url": pr_url,
                            "description": pr.get("description", ""),
                            "root_cause": _extract_root_cause(pr.get("description", "")),
                            "provider": "bitbucket",
                        })
                else:
                    # ── GitLab Merge Requests ──
                    base_url = "https://gitlab.com"
                    resp = await client.get(
                        f"{base_url}/api/v4/projects/{project_id}/merge_requests",
                        headers={"Authorization": f"Bearer {token}"},
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
                            "provider": "gitlab",
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
    """Get a single merge request / pull request with its diff."""
    token = await _get_user_token(user.id)
    project_config, provider = await _get_project_provider(project_id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "bitbucket":
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if not workspace or not repo_slug:
                if "/" in project_id:
                    workspace, repo_slug = project_id.split("/", 1)

            # PR detail
            resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{mr_iid}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Pull request not found")
            resp.raise_for_status()
            pr = resp.json()

            # PR diff
            diff_resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{mr_iid}/diffstat",
                headers={"Authorization": f"Bearer {token}"},
            )
            changes = diff_resp.json().get("values", []) if diff_resp.status_code == 200 else []

            return {"merge_request": pr, "changes": changes}
        else:
            base_url = "https://gitlab.com"
            # MR detail
            resp = await client.get(
                f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Merge request not found")
            resp.raise_for_status()
            mr = resp.json()

            # MR changes (diff)
            changes_resp = await client.get(
                f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes",
                headers={"Authorization": f"Bearer {token}"},
            )
            changes = changes_resp.json().get("changes", []) if changes_resp.status_code == 200 else []

            return {"merge_request": mr, "changes": changes}


@router.post("/{project_id}/{mr_iid}/approve")
async def approve_merge_request(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Approve a merge request (GitLab) or pull request (Bitbucket)."""
    token = await _get_user_token(user.id)
    project_config, provider = await _get_project_provider(project_id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "bitbucket":
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if not workspace or not repo_slug:
                if "/" in project_id:
                    workspace, repo_slug = project_id.split("/", 1)

            resp = await client.post(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{mr_iid}/approve",
                headers={"Authorization": f"Bearer {token}"},
            )
        else:
            resp = await client.post(
                f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/approve",
                headers={"Authorization": f"Bearer {token}"},
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
    """Merge a merge request (GitLab) or pull request (Bitbucket)."""
    token = await _get_user_token(user.id)
    project_config, provider = await _get_project_provider(project_id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "bitbucket":
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if not workspace or not repo_slug:
                if "/" in project_id:
                    workspace, repo_slug = project_id.split("/", 1)

            resp = await client.post(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{mr_iid}/merge",
                headers={"Authorization": f"Bearer {token}"},
            )
        else:
            resp = await client.put(
                f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/merge",
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        if resp.status_code == 405:
            raise HTTPException(status_code=405, detail="Cannot be merged")
        resp.raise_for_status()

    return {"status": "merged", "mr_iid": mr_iid}


@router.post("/{project_id}/{mr_iid}/reject")
async def reject_merge_request(
    project_id: str,
    mr_iid: int,
    user: UserResponse = Depends(get_current_user),
):
    """Close/reject a merge request (GitLab) or decline a pull request (Bitbucket)."""
    token = await _get_user_token(user.id)
    project_config, provider = await _get_project_provider(project_id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "bitbucket":
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if not workspace or not repo_slug:
                if "/" in project_id:
                    workspace, repo_slug = project_id.split("/", 1)

            resp = await client.post(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{mr_iid}/decline",
                headers={"Authorization": f"Bearer {token}"},
            )
        else:
            resp = await client.put(
                f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
                headers={"Authorization": f"Bearer {token}"},
                json={"state_event": "close"},
            )

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Merge request not found")
        resp.raise_for_status()

    return {"status": "rejected", "mr_iid": mr_iid}


def _extract_root_cause(description: str) -> str:
    """Extract root cause from Axolotl's MR/PR description format."""
    if not description:
        return "—"
    for line in description.split("\n"):
        if "**Root Cause:**" in line:
            return line.replace("**Root Cause:**", "").strip()
    return "—"


