"""
Bitbucket API Client
Handles authentication and communication with Bitbucket Cloud REST API 2.0
using credentials from MongoDB.
"""

from typing import Optional, Dict, Any, List
import httpx
from db.mongo_service import MongoDBService


class BitbucketAPIClient:
    """Bitbucket Cloud client that retrieves credentials from MongoDB."""

    BASE_URL = "https://api.bitbucket.org/2.0"

    def __init__(self, mongo_service: MongoDBService):
        """
        Initialize Bitbucket API Client.

        Args:
            mongo_service: MongoDBService instance for credential lookup
        """
        self.mongo_service = mongo_service
        self._tokens: Dict[str, str] = {}  # Cache tokens by project_id

    async def _get_auth_headers(self, project_id: str) -> Optional[Dict[str, str]]:
        """
        Get authorization headers for a Bitbucket project.

        Resolves the access token from the linked user (OAuth) or falls back
        to the app password stored on the project itself.

        Args:
            project_id: Internal project ID (stored in MongoDB)

        Returns:
            Dict with Authorization header, or None if project not found
        """
        print(f"[DEBUG] _get_auth_headers called | project_id={project_id}")

        # Check cache first
        if project_id in self._tokens:
            print(f"[DEBUG] Using cached Bitbucket token for project {project_id}")
            return {"Authorization": f"Bearer {self._tokens[project_id]}"}

        # Retrieve project configuration from MongoDB
        project_config = await self.mongo_service.get_project_by_id(project_id)
        if not project_config:
            print(f"[ERROR] Project {project_id} not found in MongoDB")
            return None

        # Resolve token: prefer user's OAuth token, fall back to project-level app password
        access_token = ""
        if "user_id" in project_config:
            user = await self.mongo_service.get_user_by_id(project_config["user_id"])
            if user:
                access_token = user.get("access_token", "")
                print(f"[DEBUG] Using OAuth token from linked user {user.get('username')}")
            else:
                print(f"[WARN] Linked user {project_config['user_id']} not found. Falling back to project token.")
                access_token = project_config.get("access_token", "")
        else:
            access_token = project_config.get("access_token", "")

        if not access_token:
            print(f"[ERROR] No access token found for project {project_id}")
            return None

        token_preview = f"{access_token[:10]}...{access_token[-4:]}" if len(access_token) > 14 else "***"
        print(
            f"[DEBUG] MongoDB config for project {project_id}:\n"
            f"  workspace  = {project_config.get('workspace')}\n"
            f"  repo_slug  = {project_config.get('repo_slug')}\n"
            f"  token      = {token_preview}\n"
            f"  project_name = {project_config.get('project_name', 'N/A')}"
        )

        self._tokens[project_id] = access_token
        return {"Authorization": f"Bearer {access_token}"}

    def _get_project_repo_path(self, project_config: Dict[str, Any]) -> str:
        """Build the workspace/repo_slug path from project config."""
        workspace = project_config.get("workspace", "")
        repo_slug = project_config.get("repo_slug", "")
        return f"{workspace}/{repo_slug}"

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

        headers = await self._get_auth_headers(project_id)
        if not headers:
            raise RuntimeError(
                f"Failed to get auth for project {project_id} — check MongoDB config"
            )

        project_config = await self.mongo_service.get_project_by_id(project_id)
        repo_path = self._get_project_repo_path(project_config)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Fetch pipeline steps
                print(f"[DEBUG] Fetching steps for pipeline {pipeline_uuid}")
                steps_resp = await client.get(
                    f"{self.BASE_URL}/repositories/{repo_path}/pipelines/{pipeline_uuid}/steps/",
                    headers=headers,
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

                # Filter for failed steps
                import asyncio

                failed_steps = []
                max_retries = 12  # up to 60 seconds

                for attempt in range(max_retries):
                    steps_resp = await client.get(
                        f"{self.BASE_URL}/repositories/{repo_path}/pipelines/{pipeline_uuid}/steps/",
                        headers=headers,
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
                            headers=headers,
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

        headers = await self._get_auth_headers(project_id)
        if not headers:
            return None

        project_config = await self.mongo_service.get_project_by_id(project_id)
        repo_path = self._get_project_repo_path(project_config)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers["Content-Type"] = "application/json"
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/refs/branches",
                    headers=headers,
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

        headers = await self._get_auth_headers(project_id)
        if not headers:
            return None

        project_config = await self.mongo_service.get_project_by_id(project_id)
        repo_path = self._get_project_repo_path(project_config)

        # Get author info
        author_name = project_config.get("author_name", "Axolotl Agent")
        author_email = project_config.get("author_email", "agent@axolotl.local")
        print(f"[DEBUG] Author configured: {author_name} <{author_email}>")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Bitbucket uses form-encoded POST to /src for file commits
                # Do NOT set Content-Type in headers — httpx will set multipart boundary
                auth_headers = {"Authorization": headers["Authorization"]}
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/src",
                    headers=auth_headers,
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

        headers = await self._get_auth_headers(project_id)
        if not headers:
            return None

        project_config = await self.mongo_service.get_project_by_id(project_id)
        repo_path = self._get_project_repo_path(project_config)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers["Content-Type"] = "application/json"
                resp = await client.post(
                    f"{self.BASE_URL}/repositories/{repo_path}/pullrequests",
                    headers=headers,
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
