from agents.base_agent import BaseAgent
from schemas.fix import FixProposal


class CIFixAgent(BaseAgent):
    """Simple MVP agent for supported CI failure patterns."""

    async def analyze(self, logs: str) -> FixProposal:
        text = logs.lower()

        if "modulenotfounderror" in text:
            return FixProposal(
                root_cause="Missing Python dependency in the environment.",
                file_path="requirements.txt",
                updated_content="Add the missing package to requirements.txt.",
                commit_message="fix: add missing dependency",
            )

        if "format" in text or "black" in text or "ruff format" in text:
            return FixProposal(
                root_cause="Code formatting failure detected.",
                file_path="pyproject.toml",
                updated_content="Run the formatter (Black or Ruff) and commit the formatted files.",
                commit_message="fix: format code with formatter",
            )

        if "lint" in text or "flake8" in text or "ruff" in text:
            return FixProposal(
                root_cause="Lint violation detected in the codebase.",
                file_path="src/",
                updated_content="Apply the suggested lint fixes to the failing files.",
                commit_message="fix: resolve lint issues",
            )

        return FixProposal(
            root_cause="Unsupported or unclear CI failure.",
            file_path="",
            updated_content="",
            commit_message="fix: investigate CI failure",
        )
