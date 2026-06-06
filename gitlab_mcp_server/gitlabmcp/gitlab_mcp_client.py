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
        # Check cache first
        if project_id in self.clients:
            return self.clients[project_id]
        
        # Retrieve project configuration from MongoDB
        project_config = await self.mongo_service.get_project_by_id(project_id)
        
        if not project_config:
            print(f"Project {project_id} not found in MongoDB")
            return None
        
        try:
            # Create GitLab client
            client = gitlab.Gitlab(
                url=project_config["gitlab_url"],
                private_token=project_config["access_token"]
            )
            
            # Verify connection
            client.auth()
            
            # Cache the client
            self.clients[project_id] = client
            print(f"Successfully created GitLab client for project {project_id}")
            
            return client
        except Exception as e:
            print(f"Failed to create GitLab client for project {project_id}: {e}")
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
        client = await self._get_or_create_client(project_id)
        if not client:
            return None
        
        try:
            project = client.projects.get(project_id)
            pipeline = project.pipelines.get(pipeline_id)
            jobs = pipeline.jobs.list(status="failed", all=True)
            
            if not jobs:
                print(f"No failed jobs found in pipeline {pipeline_id}")
                return None
            
            failed_jobs_data = []
            for job in jobs:
                try:
                    job_trace = job.trace()
                    failed_jobs_data.append({
                        "job_id": job.id,
                        "job_name": job.name,
                        "status": job.status,
                        "stage": job.stage,
                        "trace": job_trace.decode("utf-8") if isinstance(job_trace, bytes) else job_trace,
                    })
                except Exception as e:
                    print(f"Failed to get trace for job {job.id}: {e}")
            
            return {
                "pipeline_id": pipeline_id,
                "status": pipeline.status,
                "failed_jobs": failed_jobs_data,
            }
        
        except Exception as e:
            print(f"Failed to get pipeline logs: {e}")
            return None
    
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
        client = await self._get_or_create_client(project_id)
        if not client:
            return None
        
        try:
            project = client.projects.get(project_id)
            branch = project.branches.create({
                "branch": new_branch_name,
                "ref": source_branch,
            })
            
            print(f"Successfully created branch {new_branch_name}")
            return {
                "name": branch.name,
                "commit": branch.commit["id"],
                "protected": branch.protected,
            }
        
        except Exception as e:
            print(f"Failed to create branch: {e}")
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
        client = await self._get_or_create_client(project_id)
        if not client:
            return None
        
        try:
            project = client.projects.get(project_id)
            
            # Get project config for author info
            project_config = await self.mongo_service.get_project_by_id(project_id)
            author_name = project_config.get("author_name", "Axolotl Agent")
            author_email = project_config.get("author_email", "agent@axolotl.local")
            
            # Get or create file
            try:
                file_obj = project.files.get(file_path, ref=branch)
                file_obj.content = content
                commit = file_obj.save(
                    branch=branch,
                    commit_message=commit_message,
                    author_name=author_name,
                    author_email=author_email,
                )
            except gitlab.exceptions.GitlabGetError:
                # File doesn't exist, create it
                file_obj = project.files.create({
                    "file_path": file_path,
                    "branch": branch,
                    "content": content,
                    "commit_message": commit_message,
                    "author_name": author_name,
                    "author_email": author_email,
                })
                commit = file_obj
            
            print(f"Successfully updated file {file_path} on branch {branch}")
            return {
                "file_path": file_path,
                "branch": branch,
                "commit_message": commit_message,
                "committed": True,
            }
        
        except Exception as e:
            print(f"Failed to update file: {e}")
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
        client = await self._get_or_create_client(project_id)
        if not client:
            return None
        
        try:
            project = client.projects.get(project_id)
            mr = project.mergerequests.create({
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            })
            
            print(f"Successfully created merge request {mr.iid}")
            return {
                "iid": mr.iid,
                "title": mr.title,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "web_url": mr.web_url,
            }
        
        except Exception as e:
            print(f"Failed to create merge request: {e}")
            return None
