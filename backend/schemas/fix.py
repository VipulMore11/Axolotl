from dataclasses import dataclass


@dataclass
class FixProposal:
    """Structured result returned by the CI-fix agent."""

    root_cause: str
    file_path: str
    updated_content: str
    commit_message: str
