from dataclasses import dataclass
from typing import Optional


@dataclass
class FixProposal:
    """Structured result returned by the CI-fix agent."""

    root_cause: str
    file_path: str
    updated_content: str
    commit_message: str
    validation_passed: Optional[bool] = None
    validation_output: Optional[str] = None
    validation_attempts: Optional[int] = None
