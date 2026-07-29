"""
Bitbucket API Client (POC — App Password Auth)
Handles communication with Bitbucket Cloud REST API 2.0
using App Password (HTTP Basic Auth) from environment variables.

No OAuth required. Credentials come from:
  - BITBUCKET_USERNAME  (env)
  - BITBUCKET_APP_PASSWORD (env)
  - BITBUCKET_WORKSPACE (env, default workspace)
"""

import os
from typing import Optional, Dict, Any

import httpx
from db.mongo_service import MongoDBService


class BitbucketAPIClient:
    """Bitbucket Cloud client using App Password (HTTP Basic Auth)."""

    BASE_URL = "https://api.bitbucket.org/2.0"

    def __init__(self, mongo_service: MongoDBService):
        """
        Initialize Bitbucket API Client.

        Args:
            mongo_service: MongoDBService instance for project config lookup
        """
        self.mongo_service = mongo_service
        self._username = os.getenv("BITBUCKET_USERNAME", "")
        self._app_password = os.getenv("BITBUCKET_APP_PASSWORD", "")
        self._default_workspace = os.getenv("BITBUCKET_WORKSPACE", "")

        if not self._username or not self._app_password:
            print("[WARN] BITBUCKET_USERNAME or BITBUCKET_APP_PASSWORD not set in .env")

    @property
    def _auth(self) -> tuple[str, str]:
        """HTTP Basic Auth tuple for httpx."""
        return (self._username, self._app_password)

    async def _get_repo_path(self, project_id: str) -> str:
        """
        Resolve workspace/repo_slug from project_id.

        Tries:
          1. Project config in MongoDB (workspace + repo_slug fields)
          2. project_id itself if it looks like "workspace/repo_slug"
          3. BITBUCKET_WORKSPACE env + project_id as repo_slug
        """
        project_config = await self.mongo_service.get_project_by_id(project_id)
        if project_config:
            workspace = project_config.get("workspace", "")
            repo_slug = project_config.get("repo_slug", "")
            if workspace and repo_slug:
                return f"{workspace}/{repo_slug}"

        # project_id might already be "workspace/repo_slug"
        if "/" in project_id:
            return project_id

        # Fallback to default workspace
        if self._default_workspace:
            return f"{self._default_workspace}/{project_id}"

        raise RuntimeError(
            f"Cannot resolve repo path for project {project_id}. "
            f"Set BITBUCKET_WORKSPACE in .env or store workspace/repo_slug in MongoDB."
        )

    async def get_pipeline_logs(
        self, project_id: str, pipeline_uuid: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get logs for all failed steps in a Bitbucket pipeline.

        Args:
            project_id: Internal project ID
            pipeline_uuid: Bitbucket pipeline UUID

        Returns:
            Dictionary with step info and logs, or None if failed
        """
        print(
            f"[DEBUG] get_pipeline_logs called | "
            f"project_id={project_id} | pipeline_uuid={pipeline_uuid}"
        )

        repo_path = await self._get_repo_path(project_id)

        try:
            async with httpx.AsyncClient(timeout=30.0, auth=self._auth) as client:
                # Fetch pipeline steps
                print(f"[DEBUG] Fetching steps for pipeline {pipeline_uuid}")
                steps_resp = await client.get(
                    f"{self.BASE_URL}/repositories/{repo_path}/pipelines/{pipeline_uuid}/steps/",
                    params={"pagelen": 100},
                )
                steps_resp.raise_for_status()
                steps_data = steps_resp.json()
                steps = steps_data.get("values", [])

                print(f"[DEBUG] Found {len(steps)} steps")
                for step in steps:
                    state = step.get("state", {})
                    result = state.get("result", {})
                    step_name = step.get("name", "unnamed")
                    step_status = result.get("name", state.get("name", "unknown"))
                    print(f"[DEBUG] Step '{step_name}' | status={step_status}")

                # Poll for failed steps (pipeline may still be completing)
                import asyncio

                failed_steps = []
                max_retries = 12  # up to 60 seconds

                for attempt in range(max_retries):
                    steps_resp = await client.get(
                        f"{self.BASE_URL}/repositories/{repo_path}/pipelines/{pipeline_uuid}/steps/",
                        params={"pagelen": 100},
                    )
                    steps_resp.raise_for_status()
                    steps = steps_resp.json().get("values", [])

                    failed_steps = [
                        s for s in steps
                        if s.get("state", {}).get("result", {}).get("name") == "FAILED"
                    ]

                    if failed_steps:
                        print(f"[DEBUG] Found {len(failed_steps)} failed steps!")
                        break

                    print(f"[DEBUG] No failed steps found yet (attempt {attempt + 1}/{max_retries}). Waiting 5 seconds...")
                    await asyncio.sleep(5)

                if not failed_steps:
                    print(f"[WARN] No failed steps found in pipeline {pipeline_uuid} after {max_retries} attempts.")
                    return None

                # Fetch logs for each failed step
                failed_jobs_data = []
                for step in failed_steps:
                    step_uuid = step.get("uuid", "").strip("{}")
                    step_name = step.get("name", "unnamed")
                    print(f"[DEBUG] Fetching log for step '{step_name}' (uuid={step_uuid})")

                    try:
                        log_resp = await client.get(
                            f"{self.BASE_URL}/repositories/{repo_path}/pipelines/{pipeline_uuid}/steps/{{{step_uuid}}}/log",
                        )
                        if log_resp.status_code == 200:
                            trace_text = log_resp.text
                            print(f"[DEBUG] Got log for step '{step_name}' (length={len(trace_text)})")
                        else:
                            trace_text = f"[Could not fetch log: HTTP {log_resp.status_code}]"
                            print(f"[WARN] Failed to get log for step '{step_name}': {log_resp.status_code}")
                    except Exception as e:
                        trace_text = f"[Error fetching log: {e}]"
                        print(f"[ERROR] Exception fetching log for step '{step_name}': {e}")

                    failed_jobs_data.append({
                        "job_id": step_uuid,
                        "job_name": step_name,
                        "status": "failed",
                        "stage": step.get("name", "unknown"),
                        "trace": trace_text,
                    })

                print(f"[DEBUG] Returning pipeline logs | failed_steps_collected={len(failed_jobs_data)}")

                return {
                    "pipeline_id": pipeline_uuid,
                    "status": "FAILED",
                    "failed_jobs": failed_jobs_data,
                }

        except Exception as e:
            print(
                f"[ERROR] Failed to get pipeline logs | "
                f"project_id={project_id} | "
                f"pipeline_uuid={pipeline_uuid} | "
                f"error={str(e)}"
            )
            raise

    async def create_branch(
        self,
        project_id: str,
        source_branch: str,
        new_branch_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new branch in the Bitbucket repository.

        Args:
            project_id: Internal project ID
            source_branch: Source branch name (e.g., "main")
            new_branch_name: Name of the new branch (e.g., "axolotl/fix/123")

        Returns:
            Branch information or None if failed
        """
        print(f"[DEBUG] create_branch called | project_id={project_id} | source_branch={source_branch} | new_branch_name={new_branch_name}")

        repo_path = await self._get_repo_path(project_id)

        try:
            async with httpx.AsyncClient(timeout=15.0, auth=self._auth) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/refs/branches",
                    json={
                        "name": new_branch_name,
                        "target": {
                            "hash": source_branch,
                        },
                    },
                )
                resp.raise_for_status()
                branch = resp.json()

                print(f"[DEBUG] Successfully created branch {new_branch_name}")
                return {
                    "name": branch.get("name", new_branch_name),
                    "commit": branch.get("target", {}).get("hash", ""),
                    "protected": False,
                }

        except Exception as e:
            print(f"[ERROR] Failed to create branch: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def search_code(
        self,
        project_id: str,
        branch: str,
        patterns: list,
        max_files: int = 200,
        max_matches: int = 50,
    ) -> Optional[Dict[str, Any]]:
        """
        Fan-out search over Bitbucket src tree for literal pattern matches.
        """
        print(
            f"[DEBUG] search_code called | project_id={project_id} | branch={branch} "
            f"| patterns={patterns[:5]} | max_files={max_files}"
        )
        if not patterns:
            return {"matches": [], "files": [], "scanned": 0}

        repo_path = await self._get_repo_path(project_id)

        try:
            from agents.error_signature import content_matches_patterns, is_searchable_path
        except Exception:
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from agents.error_signature import content_matches_patterns, is_searchable_path

        clean_patterns = [str(p) for p in patterns if p]

        async def _list_dir(client: httpx.AsyncClient, prefix: str) -> list[dict]:
            url = f"{self.BASE_URL}/repositories/{repo_path}/src/{branch}/{prefix}".rstrip("/")
            if prefix and not url.endswith("/"):
                url += "/"
            resp = await client.get(url, params={"pagelen": 100, "max_depth": 1})
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return list(data.get("values") or [])

        try:
            async with httpx.AsyncClient(timeout=30.0, auth=self._auth) as client:
                # BFS over directories to collect blob paths
                queue: list[str] = [""]
                blob_paths: list[str] = []
                seen_dirs: set[str] = set()
                while queue and len(blob_paths) < max_files:
                    prefix = queue.pop(0)
                    if prefix in seen_dirs:
                        continue
                    seen_dirs.add(prefix)
                    try:
                        entries = await _list_dir(client, prefix)
                    except Exception:
                        continue
                    for entry in entries:
                        path = str(entry.get("path") or "").lstrip("/")
                        etype = entry.get("type")
                        if etype == "commit_directory":
                            if path and is_searchable_path(path + "/file.py"):
                                # directory itself — enqueue unless skipped by prefix rules
                                pass
                            queue.append(path)
                        elif etype == "commit_file" and is_searchable_path(path):
                            blob_paths.append(path)
                            if len(blob_paths) >= max_files:
                                break

                matches: list[Dict[str, Any]] = []
                files_hit: list[str] = []
                scanned = 0
                for path in blob_paths:
                    if len(matches) >= max_matches:
                        break
                    resp = await client.get(
                        f"{self.BASE_URL}/repositories/{repo_path}/src/{branch}/{path}",
                    )
                    if resp.status_code != 200:
                        continue
                    content = resp.text
                    scanned += 1
                    hits = content_matches_patterns(content, clean_patterns)
                    if hits:
                        files_hit.append(path)
                        matches.append(
                            {
                                "file_path": path,
                                "patterns": hits[:5],
                                "snippet": next(
                                    (
                                        line.strip()
                                        for line in content.splitlines()
                                        if any(h in line for h in hits)
                                    ),
                                    hits[0],
                                )[:200],
                            }
                        )

                print(
                    f"[DEBUG] search_code done | scanned={scanned} | hits={len(files_hit)}"
                )
                return {
                    "matches": matches,
                    "files": files_hit,
                    "scanned": scanned,
                    "branch": branch,
                }

        except Exception as e:
            print(f"[ERROR] search_code failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def get_file_contents(
        self, project_id: str, branch: str, file_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch raw file contents at a given ref via GET /src/{ref}/{path}.

        Returns {"exists": False} (not None) for missing files so callers can
        distinguish "new file" from an API failure.
        """
        print(f"[DEBUG] get_file_contents called | project_id={project_id} | branch={branch} | file_path={file_path}")

        repo_path = await self._get_repo_path(project_id)

        try:
            async with httpx.AsyncClient(timeout=15.0, auth=self._auth) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/repositories/{repo_path}/src/{branch}/{file_path}",
                )
                if resp.status_code == 404:
                    print(f"[DEBUG] File {file_path} not found on branch {branch}")
                    return {
                        "file_path": file_path,
                        "branch": branch,
                        "exists": False,
                        "content": None,
                    }
                resp.raise_for_status()
                print(f"[DEBUG] Fetched {file_path} ({len(resp.text)} chars)")
                return {
                    "file_path": file_path,
                    "branch": branch,
                    "exists": True,
                    "content": resp.text,
                }

        except Exception as e:
            print(f"[ERROR] Failed to fetch file contents: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def update_file(
        self,
        project_id: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Update or create a file and commit the changes via Bitbucket API.

        Uses the POST /src endpoint which accepts form-encoded data.

        Args:
            project_id: Internal project ID
            branch: Branch to commit to
            file_path: Path to the file in the repository
            content: New file content
            commit_message: Commit message

        Returns:
            Commit information or None if failed
        """
        print(f"[DEBUG] update_file called | project_id={project_id} | branch={branch} | file_path={file_path}")

        repo_path = await self._get_repo_path(project_id)

        # Get author info from env
        author_name = os.getenv("AUTHOR_NAME", "Axolotl Agent")
        author_email = os.getenv("AUTHOR_EMAIL", "agent@axolotl.local")
        print(f"[DEBUG] Author configured: {author_name} <{author_email}>")

        try:
            async with httpx.AsyncClient(timeout=15.0, auth=self._auth) as client:
                # Bitbucket uses form-encoded POST to /src for file commits
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/src",
                    data={
                        file_path: content,
                        "message": commit_message,
                        "branch": branch,
                        "author": f"{author_name} <{author_email}>",
                    },
                )
                resp.raise_for_status()

                print(f"[DEBUG] Successfully updated file {file_path} on branch {branch}")
                return {
                    "file_path": file_path,
                    "branch": branch,
                    "commit_message": commit_message,
                    "committed": True,
                }

        except Exception as e:
            print(f"[ERROR] Failed to update file: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def create_pull_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a pull request on Bitbucket.

        Args:
            project_id: Internal project ID
            source_branch: Source branch name
            target_branch: Target branch name
            title: PR title
            description: PR description

        Returns:
            PR information or None if failed
        """
        print(f"[DEBUG] create_pull_request called | project_id={project_id} | source_branch={source_branch} | target_branch={target_branch}")

        repo_path = await self._get_repo_path(project_id)

        try:
            async with httpx.AsyncClient(timeout=15.0, auth=self._auth) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/pullrequests",
                    json={
                        "title": title,
                        "description": description,
                        "source": {
                            "branch": {
                                "name": source_branch,
                            },
                        },
                        "destination": {
                            "branch": {
                                "name": target_branch,
                            },
                        },
                        "close_source_branch": False,
                    },
                )
                resp.raise_for_status()
                pr = resp.json()

                pr_id = pr.get("id")
                print(f"[DEBUG] Successfully created pull request #{pr_id}")
                return {
                    "iid": pr_id,
                    "title": pr.get("title", title),
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "web_url": pr.get("links", {}).get("html", {}).get("href", ""),
                }

        except Exception as e:
            print(f"[ERROR] Failed to create pull request: {e}")
            import traceback
            traceback.print_exc()
            return None
