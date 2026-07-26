"""
CI fix agent facade.

Defaults to the LangGraph + Docker validation engine.
Set CI_FIX_ENGINE=legacy for the one-shot Gemini path.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import override

from dotenv import load_dotenv
from google import genai

from agents.base_agent import BaseAgent
from agents.exceptions import CIFixAgentError
from agents.prompt_builder import PromptBuilder
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure

load_dotenv()

# Re-export for existing `from agents.ci_fix_agent import CIFixAgentError` call sites
__all__ = ["CIFixAgent", "CIFixAgentError", "LegacyCIFixAgent"]


class LegacyCIFixAgent(BaseAgent):
    """One-shot Gemini CI failure analysis (no Docker validation)."""

    def __init__(self) -> None:
        self.model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=api_key)

    @override
    async def analyze(self, failure: PipelineFailure) -> FixProposal:
        """Analyze a pipeline failure and return a structured fix proposal."""
        print(
            f"[DEBUG] LegacyCIFixAgent.analyze | project_id={failure.project_id} "
            f"| pipeline_id={failure.pipeline_id}"
        )
        try:
            prompt = PromptBuilder.build_prompt(failure)
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
            )
            content = getattr(response, "text", "") or ""
            if not content:
                raise ValueError("Gemini returned an empty response")

            cleaned_content = content.strip()
            if cleaned_content.startswith("```"):
                cleaned_content = re.sub(
                    r"^```(?:json)?\s*", "", cleaned_content, flags=re.IGNORECASE | re.DOTALL
                )
                cleaned_content = re.sub(
                    r"\s*```$", "", cleaned_content, flags=re.IGNORECASE | re.DOTALL
                )

            try:
                payload = json.loads(cleaned_content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", cleaned_content, flags=re.DOTALL)
                if not match:
                    raise
                payload = json.loads(match.group(0))

            return FixProposal(
                root_cause=str(payload.get("root_cause", "AI-generated fix proposal.")),
                file_path=str(payload.get("file_path", "")),
                updated_content=str(payload.get("updated_content", "")),
                commit_message=str(payload.get("commit_message", "fix: apply AI-generated patch")),
            )
        except Exception as exc:
            raise CIFixAgentError(f"CI fix analysis failed: {exc}") from exc


def _build_engine(on_stage=None) -> BaseAgent:
    engine = (os.getenv("CI_FIX_ENGINE") or "langgraph").strip().lower()
    if engine == "legacy":
        print("[CIFixAgent] Using legacy one-shot Gemini engine")
        return LegacyCIFixAgent()

    from agents.langgraph_ci_fix_agent import LangGraphCIFixAgent

    print("[CIFixAgent] Using LangGraph eight-stage + Docker validation engine")
    return LangGraphCIFixAgent(on_stage=on_stage)


class CIFixAgent(BaseAgent):
    """
    Facade that delegates to LangGraph (default) or legacy Gemini analysis.

    Environment:
      CI_FIX_ENGINE=langgraph|legacy  (default: langgraph)
      CI_FIX_VALIDATE=true|false      (LangGraph only)
      CI_FIX_MAX_ATTEMPTS=3           (LangGraph only)
    """

    def __init__(self, on_stage=None) -> None:
        self._impl = _build_engine(on_stage=on_stage)

    def set_on_stage(self, on_stage) -> None:
        """Attach a live stage callback (used by the orchestrator for WebSocket events)."""
        if hasattr(self._impl, "set_on_stage"):
            self._impl.set_on_stage(on_stage)

    @override
    async def analyze(self, failure: PipelineFailure) -> FixProposal:
        return await self._impl.analyze(failure)
