from schemas.pipeline import PipelineFailure


class PromptBuilder:
    """Builds structured prompts for the legacy one-shot CI fix agent (LegacyCIFixAgent).

    NOTE: The LangGraph multi-stage pipeline no longer uses this class.
    It builds slim, diagnosis-only prompts inline to avoid biasing the model
    toward specific error families. Keep this class for the legacy code path.
    """

    @staticmethod
    def build_prompt(failure: PipelineFailure, logs: str | None = None) -> str:
        """
        Create a JSON-focused prompt for Gemini using the failed pipeline data.

        This is the legacy one-shot prompt shape (file_path / updated_content).
        Prefer passing a pre-reduced `logs` digest; falls back to failure.logs.
        """
        log_text = logs if logs is not None else failure.logs
        return f"""
You are an expert CI/CD analyzer for a Python project.
Analyze the following pipeline failure and return ONLY valid JSON with these exact keys:
- root_cause
- file_path
- updated_content
- commit_message

Use these MVP rules:
1. If the logs mention ModuleNotFoundError, suggest updating requirements.txt (and related files if needed).
2. If the logs mention formatting, black, or ruff format, suggest applying format fixes to affected files.
3. If the logs mention lint, flake8, or ruff, suggest applying patches to the affected files.
4. Prefer minimal multi-file edits when required; keep changes practical.
5. Keep the output concise.
6. Trust the provided log digest — it already filters CI noise; do not invent failures not present in it.

Project ID: {failure.project_id}
Pipeline ID: {failure.pipeline_id}
Branch: {failure.branch}
Relevant CI errors (compressed digest):
{log_text}
""".strip()
