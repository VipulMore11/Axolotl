import asyncio

from orchestrator.pipeline_orchestrator import PipelineOrchestrator
from schemas.pipeline import PipelineFailure


async def main() -> None:
    orchestrator = PipelineOrchestrator()

    failure = PipelineFailure(
        project_id="demo-project",
        pipeline_id="12345",
        branch="main",
        logs="ModuleNotFoundError: No module named 'pandas'",
    )

    result = await orchestrator.handle_failure(failure)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
