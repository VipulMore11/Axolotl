from schemas.pipeline import PipelineFailure


class PromptBuilder:
    """Builds structured prompts for Gemini-based CI fix analysis."""

    @staticmethod
    def build_prompt(failure: PipelineFailure) -> str:
        """Create a JSON-focused prompt for Gemini using the failed pipeline data."""
        return f"""
You are an expert CI/CD analyzer for a Python project.
Analyze the following pipeline failure and return ONLY valid JSON with these exact keys:
- root_cause
- file_path
- updated_content
- commit_message

Use these MVP rules:
1. If the logs mention ModuleNotFoundError, suggest updating requirements.txt.
2. If the logs mention formatting, black, or ruff format, suggest running Black formatter.
3. If the logs mention lint, flake8, or ruff, suggest applying a patch to the affected files.
4. Keep the output concise and practical.

Project ID: {failure.project_id}
Pipeline ID: {failure.pipeline_id}
Branch: {failure.branch}
Logs:
{failure.logs}
""".strip()
