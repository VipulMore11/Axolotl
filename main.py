import asyncio

from orchestrator.pipeline_orchestrator import PipelineOrchestrator


async def main() -> None:
    orchestrator = PipelineOrchestrator()

    result = await orchestrator.handle_pipeline_failure(
        project_id="demo-project",
        pipeline_id="12345",
        branch="main",
        logs="ModuleNotFoundError: No module named 'pandas'",
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())
