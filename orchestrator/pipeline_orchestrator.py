from agents.ci_fix_agent import CIFixAgent


class PipelineOrchestrator:
    """Starter workflow controller for the agent + CI fix pipeline."""

    def __init__(self, agent: CIFixAgent | None = None) -> None:
        self.agent = agent or CIFixAgent()

    async def handle_pipeline_failure(self, project_id: str, pipeline_id: str, branch: str, logs: str) -> dict:
        """Run the first MVP analysis step on a failed pipeline."""
        print(f"[EVENT] Pipeline failed for project={project_id}, pipeline={pipeline_id}")
        print("[EVENT] Fetching logs and starting analysis")
        fix = await self.agent.analyze(logs)
        print("[EVENT] Root cause detected")
        print(f"[EVENT] Fix generated: {fix.commit_message}")
        print("[EVENT] Creating branch for the fix")
        print("[EVENT] Committing the fix")
        print("[EVENT] Creating merge request")
        print("[EVENT] Waiting for human approval")

        return {
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "branch": branch,
            "status": "analysis_complete",
            "fix": {
                "root_cause": fix.root_cause,
                "file_path": fix.file_path,
                "updated_content": fix.updated_content,
                "commit_message": fix.commit_message,
            },
        }
