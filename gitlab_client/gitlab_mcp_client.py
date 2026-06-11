"""
GitLab MCP Client
Handles authentication and communication with GitLab API using credentials from MongoDB.
"""

from typing import Optional, Dict, Any, List
import gitlab
from db.mongo_service import MongoDBService


class GitLabMCPClient:
    """GitLab client that retrieves credentials from MongoDB."""

    def __init__(self, mongo_service: MongoDBService):
        """
        Initialize GitLab MCP Client.

        Args:
            mongo_service: MongoDBService instance for credential lookup
        """
        self.mongo_service = mongo_service
        self.clients: Dict[str, gitlab.Gitlab] = {}  # Cache clients by project_id

    async def _get_or_create_client(self, project_id: str) -> Optional[gitlab.Gitlab]:
        """
        Get or create a GitLab client for a specific project.

        Args:
            project_id: GitLab project ID

        Returns:
            gitlab.Gitlab client instance or None if project not found
        """
        print(f"[DEBUG] _get_or_create_client called | project_id={project_id} (type={type(project_id).__name__})")

        # Check cache first
        if project_id in self.clients:
            print(f"[DEBUG] Using cached GitLab client for project {project_id}")
            return self.clients[project_id]

        # Retrieve project configuration from MongoDB
        project_config = await self.mongo_service.get_project_by_id(project_id)

        if not project_config:
            print(f"[ERROR] Project {project_id} not found in MongoDB")
            return None

        # ── Debug: dump the MongoDB record being used ──
        token = project_config.get("access_token", "")
        token_preview = f"{token[:10]}...{token[-4:]}" if len(token) > 14 else "***"
        print(
            f"[DEBUG] MongoDB config for project {project_id}:\n"
            f"  project_id (from DB) = {project_config.get('project_id')} (type={type(project_config.get('project_id')).__name__})\n"
            f"  gitlab_url           = {project_config.get('gitlab_url')}\n"
            f"  access_token         = {token_preview}\n"
            f"  project_name         = {project_config.get('project_name', 'N/A')}\n"
            f"  author_name          = {project_config.get('author_name', 'N/A')}"
        )

        try:
            # Create GitLab client
            client = gitlab.Gitlab(
                url=project_config["gitlab_url"],
                private_token=project_config["access_token"]
            )

            # Verify connection
            print(f"[DEBUG] Authenticating GitLab client at {project_config['gitlab_url']}...")
            client.auth()
            print(f"[DEBUG] Auth successful. Authenticated as: {client.user.username}")

            # Cache the client
            self.clients[project_id] = client
            print(f"[DEBUG] Successfully created and cached GitLab client for project {project_id}")

            return client
        except Exception as e:
            print(f"[ERROR] Failed to create GitLab client for project {project_id}: {e}")
            return None

    async def get_pipeline_logs(self, project_id: str, pipeline_id: str) -> Optional[Dict[str, Any]]:
        """
        Get logs for all failed jobs in a pipeline.

        Args:
            project_id: GitLab project ID
            pipeline_id: GitLab pipeline ID

        Returns:
            Dictionary with job info and logs, or None if failed
        """

        print(
            f"[DEBUG] get_pipeline_logs called | "
            f"project_id={project_id} | pipeline_id={pipeline_id}"
        )

        client = await self._get_or_create_client(project_id)

        if not client:
            raise RuntimeError(f"Failed to create GitLab client for project {project_id} — check MongoDB config and GitLab access token")

        try:
            print(f"[DEBUG] Fetching project {project_id}")
            project = client.projects.get(project_id)

            print(f"[DEBUG] Fetching pipeline {pipeline_id}")
            pipeline = project.pipelines.get(pipeline_id)

            print(
                f"[DEBUG] Pipeline found | "
                f"id={pipeline.id} | status={pipeline.status} | ref={pipeline.ref}"
            )

            import asyncio

            failed_jobs = []
            max_retries = 12  # up to 60 seconds

            for attempt in range(max_retries):
                print(f"[DEBUG] Fetching jobs (Attempt {attempt + 1}/{max_retries})...")
                jobs = pipeline.jobs.list(all=True)

                for job in jobs:
                    print(f"[DEBUG] Job {job.id} | {job.name} | {job.status}")

                # Filter for failed jobs
                failed_jobs = [job for job in jobs if job.status == "failed"]

                if failed_jobs:
                    print(f"[DEBUG] Found {len(failed_jobs)} failed jobs!")
                    break

                print(f"[DEBUG] No failed jobs found yet. Pipeline status is {pipeline.status}. Waiting 5 seconds...")
                await asyncio.sleep(5)
                # Refresh pipeline object to get updated status
                pipeline = project.pipelines.get(pipeline_id)

            if not failed_jobs:
                print(
                    f"[WARN] No failed jobs found in pipeline {pipeline_id} after {max_retries} attempts. "
                    f"Final Pipeline status = {pipeline.status}"
                )
                return None
            failed_jobs_data = []
            for job in failed_jobs:
                print(
                    f"[DEBUG] Processing failed job | "
                    f"id={job.id} | name={job.name} | "
                    f"stage={job.stage} | status={job.status}"
                )

                import asyncio
                job_trace = b""
                trace_success = False
                
                for trace_attempt in range(5):
                    try:
                        print(f"[DEBUG] Fetching trace for job {job.id} (Attempt {trace_attempt+1}/5)")
                        # python-gitlab requires fetching the full object via get() before calling trace()
                        full_job = project.jobs.get(job.id)
                        job_trace = full_job.trace()
                        trace_success = True
                        break
                    except Exception as e:
                        print(f"[WARN] Failed to get trace for job {job.id} on attempt {trace_attempt+1}: {str(e)}")
                        if trace_attempt < 4:
                            print("[DEBUG] Waiting 3 seconds before retrying trace...")
                            await asyncio.sleep(3)
                        else:
                            print(f"[ERROR] Completely failed to fetch trace for job {job.id} after 5 attempts.")
                            raise  # Re-raise so the MCP server catches it and reports back to the orchestrator

                if trace_success:
                    trace_text = (
                        job_trace.decode("utf-8")
                        if isinstance(job_trace, bytes)
                        else job_trace
                    )

                    print(
                        f"[DEBUG] Successfully fetched trace for job {job.id} "
                        f"(length={len(trace_text)} chars)"
                    )

                    failed_jobs_data.append({
                        "job_id": job.id,
                        "job_name": job.name,
                        "status": job.status,
                        "stage": job.stage,
                        "trace": trace_text,
                    })

            print(
                f"[DEBUG] Returning pipeline logs | "
                f"failed_jobs_collected={len(failed_jobs_data)}"
            )

            return {
                "pipeline_id": pipeline_id,
                "status": pipeline.status,
                "failed_jobs": failed_jobs_data,
            }

        except Exception as e:
            print(
                f"[ERROR] Failed to get pipeline logs | "
                f"project_id={project_id} | "
                f"pipeline_id={pipeline_id} | "
                f"error={str(e)}"
            )
            raise

    async def create_branch(self, project_id: str, source_branch: str, new_branch_name: str) -> Optional[Dict[str, Any]]:
        """
        Create a new branch in the repository.

        Args:
            project_id: GitLab project ID
            source_branch: Source branch name (e.g., "main")
            new_branch_name: Name of the new branch (e.g., "axolotl/fix/123")

        Returns:
            Branch information or None if failed
        """
        print(f"[DEBUG] create_branch called | project_id={project_id} | source_branch={source_branch} | new_branch_name={new_branch_name}")

        client = await self._get_or_create_client(project_id)
        if not client:
            return None

        try:
            print(f"[DEBUG] Fetching project {project_id} for branch creation")
            project = client.projects.get(project_id)
            print(f"[DEBUG] Creating branch {new_branch_name} from {source_branch}")
            branch = project.branches.create({
                "branch": new_branch_name,
                "ref": source_branch,
            })

            print(f"[DEBUG] Successfully created branch {new_branch_name}")
            return {
                "name": branch.name,
                "commit": branch.commit["id"],
                "protected": branch.protected,
            }

        except Exception as e:
            print(f"[ERROR] Failed to create branch: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def update_file(self, project_id: str, branch: str, file_path: str, content: str, commit_message: str) -> Optional[Dict[str, Any]]:
        """
        Update or create a file and commit the changes.

        Args:
            project_id: GitLab project ID
            branch: Branch name to commit to
            file_path: Path to the file in the repository
            content: New file content
            commit_message: Commit message

        Returns:
            Commit information or None if failed
        """
        print(f"[DEBUG] update_file called | project_id={project_id} | branch={branch} | file_path={file_path}")

        client = await self._get_or_create_client(project_id)
        if not client:
            return None

        try:
            print(f"[DEBUG] Fetching project {project_id} for file update")
            project = client.projects.get(project_id)

            # Get project config for author info
            project_config = await self.mongo_service.get_project_by_id(project_id)
            author_name = project_config.get("author_name", "Axolotl Agent")
            author_email = project_config.get("author_email", "agent@axolotl.local")
            print(f"[DEBUG] Author configured: {author_name} <{author_email}>")

            # Get or create file
            try:
                print(f"[DEBUG] Attempting to get existing file {file_path}")
                file_obj = project.files.get(file_path, ref=branch)
                file_obj.content = content
                print(f"[DEBUG] Updating existing file {file_path}")
                commit = file_obj.save(
                    branch=branch,
                    commit_message=commit_message,
                    author_name=author_name,
                    author_email=author_email,
                )
            except gitlab.exceptions.GitlabGetError:
                # File doesn't exist, create it
                print(f"[DEBUG] File {file_path} not found. Creating new file.")
                file_obj = project.files.create({
                    "file_path": file_path,
                    "branch": branch,
                    "content": content,
                    "commit_message": commit_message,
                    "author_name": author_name,
                    "author_email": author_email,
                })
                commit = file_obj

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

    async def create_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a merge request.

        Args:
            project_id: GitLab project ID
            source_branch: Source branch name
            target_branch: Target branch name
            title: MR title
            description: MR description

        Returns:
            MR information or None if failed
        """
        print(f"[DEBUG] create_merge_request called | project_id={project_id} | source_branch={source_branch} | target_branch={target_branch}")

        client = await self._get_or_create_client(project_id)
        if not client:
            return None

        try:
            print(f"[DEBUG] Fetching project {project_id} for MR creation")
            project = client.projects.get(project_id)
            print(f"[DEBUG] Creating merge request from {source_branch} to {target_branch}")
            mr = project.mergerequests.create({
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            })

            print(f"[DEBUG] Successfully created merge request {mr.iid}")
            return {
                "iid": mr.iid,
                "title": mr.title,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "web_url": mr.web_url,
            }

        except Exception as e:
            print(f"[ERROR] Failed to create merge request: {e}")
            import traceback
            traceback.print_exc()
            return None
