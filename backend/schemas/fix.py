from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FilePatch:
    """One file changed by the CI-fix agent."""

    file_path: str
    updated_content: str


@dataclass
class FixProposal:
    """Structured result returned by the CI-fix agent (multi-file capable)."""

    root_cause: str
    commit_message: str
    file_patches: list[FilePatch] = field(default_factory=list)
    # Backward-compatible single-file views (first patch)
    file_path: str = ""
    updated_content: str = ""
    validation_passed: Optional[bool] = None
    validation_output: Optional[str] = None
    validation_attempts: Optional[int] = None
    architecture_plan: Optional[dict] = None
    kb_grounding: Optional[str] = None

    def __post_init__(self) -> None:
        if self.file_patches:
            if not self.file_path:
                self.file_path = self.file_patches[0].file_path
            if not self.updated_content:
                self.updated_content = self.file_patches[0].updated_content
        elif self.file_path:
            # Legacy construction path
            self.file_patches = [
                FilePatch(file_path=self.file_path, updated_content=self.updated_content)
            ]
