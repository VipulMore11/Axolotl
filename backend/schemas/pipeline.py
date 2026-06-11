from dataclasses import dataclass


@dataclass
class PipelineFailure:
    """Structured representation of a failed CI pipeline run."""

    project_id: str
    pipeline_id: str
    branch: str
    logs: str
