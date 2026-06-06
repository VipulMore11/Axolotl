import asyncio
from typing import Callable, Optional

from agents.ci_fix_agent import CIFixAgent, CIFixAgentError
from orchestrator.event_types import EventType
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure


class PipelineOrchestrator:
    """Coordinates pipeline failure analysis and fix proposal generation."""

    def __init__(
        self,
        ci_fix_agent: Optional[CIFixAgent] = None,
        gitlab_service: Optional[object] = None,
        event_publisher: Optional[Callable[[EventType, str], None]] = None,
    ) -> None:
        self.ci_fix_agent = ci_fix_agent or CIFixAgent()
        self.gitlab_service = gitlab_service
        self.event_publisher = event_publisher or (lambda *_args, **_kwargs: None)

    async def _publish_event(self, event_type: EventType, message: str) -> None:
        """Publish an orchestration event, supporting both sync and async publishers."""
        print(f"[EVENT] {event_type.value}: {message}")
        publisher = self.event_publisher
        result = publisher(event_type, message)
        if asyncio.isfuture(result):
            await result

    async def handle_failure(self, failure: PipelineFailure) -> FixProposal:
        """Run the analysis flow for a failed pipeline and emit orchestration events."""
        try:
            await self._publish_event(EventType.PIPELINE_FAILED, f"Pipeline {failure.pipeline_id} failed on {failure.branch}.")
            await self._publish_event(EventType.ANALYZING, "Starting CI fix analysis.")
            fix = await self.ci_fix_agent.analyze(failure)
            await self._publish_event(EventType.GENERATING_FIX, f"Generated fix for {fix.file_path}.")
            return fix
        except Exception as exc:
            await self._publish_event(EventType.FIX_FAILED, f"Fix generation failed: {exc}")
            raise CIFixAgentError(f"Pipeline orchestration failed: {exc}") from exc

    async def handle_pipeline_failure(self, project_id: str, pipeline_id: str, branch: str, logs: str) -> dict:
        """Backward-compatible wrapper for the original pipeline failure entry point."""
        failure = PipelineFailure(project_id=project_id, pipeline_id=pipeline_id, branch=branch, logs=logs)
        fix = await self.handle_failure(failure)
        return {
            "project_id": failure.project_id,
            "pipeline_id": failure.pipeline_id,
            "branch": failure.branch,
            "status": "analysis_complete",
            "fix": {
                "root_cause": fix.root_cause,
                "file_path": fix.file_path,
                "updated_content": fix.updated_content,
                "commit_message": fix.commit_message,
            },
        }
