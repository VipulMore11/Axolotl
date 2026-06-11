import asyncio
import json
import os
import re
from typing import override

from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent

from agents.base_agent import BaseAgent
from agents.prompt_builder import PromptBuilder
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure

load_dotenv()


class CIFixAgentError(RuntimeError):
    """Raised when CI fix analysis fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CIFixAgent(BaseAgent):
    """CI failure analysis agent backed by Gemini and ADK."""

    def __init__(self, model: str = "gemini-2.5-flash") -> None:
        """Initialize the Gemini client and ADK agent wrapper."""
        self.model = model
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=api_key)
        self.adk_agent = Agent(
            name="ci_fix_agent",
            model=model,
            instruction="You are a CI/CD failure analyst. Return only valid JSON.",
        )

    @override
    async def analyze(self, failure: PipelineFailure) -> FixProposal:
        """Analyze a pipeline failure and return a structured fix proposal."""
        print(f"[DEBUG] ci_fix_agent.analyze called | project_id={failure.project_id} | pipeline_id={failure.pipeline_id}")
        try:
            print(f"[DEBUG] Building prompt for Gemini. Log length: {len(failure.logs)}")
            prompt = PromptBuilder.build_prompt(failure)
            
            print(f"[DEBUG] Calling Gemini API with model: {self.model}")
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
            )
            print("[DEBUG] Gemini API returned successfully")
            content = getattr(response, "text", "") or ""
            if not content:
                raise ValueError("Gemini returned an empty response")

            cleaned_content = content.strip()
            if cleaned_content.startswith("```"):
                cleaned_content = re.sub(r"^```(?:json)?\s*", "", cleaned_content, flags=re.IGNORECASE | re.DOTALL)
                cleaned_content = re.sub(r"\s*```$", "", cleaned_content, flags=re.IGNORECASE | re.DOTALL)

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
