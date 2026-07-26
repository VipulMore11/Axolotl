"""
LangGraph CI fix agent — eight-stage Evaluator-Optimizer pipeline.

Artifact contracts (not chat transcripts) pass between persona nodes:
  Analyst (Flash) → Architect (Pro) → Tech Lead (Flash) → Developer (Pro)
  → Docker validate → Evaluator (Pro) ⇄ Developer on failure.

Stage 8 (git_operations) runs in the orchestrator via MCP after FixProposal.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Optional, override

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from pydantic import BaseModel, Field

from agents.base_agent import BaseAgent
from agents.ci_fix_state import (
    ArchitecturePlan,
    CIFixState,
    CritiqueResult,
    empty_architecture_plan,
)
from agents.exceptions import CIFixAgentError
from agents.langsmith_tracing import build_run_config, configure_langsmith
from agents.prompt_builder import PromptBuilder
from agents.sandbox_tools import cleanup_workspace, reset_workspace, validate_patch
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure

load_dotenv()

StageCallback = Callable[[str, str, Optional[dict]], Awaitable[None] | None]

# ── Pydantic mirrors of artifact contracts (structured LLM output) ──


class DiagnosisResult(BaseModel):
    root_cause: str = Field(description="Concise root cause of the CI failure")


class ArchitecturePlanModel(BaseModel):
    strategy_type: str = Field(
        description="One of: deps, lint, format, code_patch"
    )
    affected_files: list[str] = Field(
        description="Relative file paths expected to change (prefer one)"
    )
    proposed_solution: str = Field(
        description="Low-blast-radius solution summary"
    )


class TaskBreakdownResult(BaseModel):
    task_breakdown: list[str] = Field(
        description="Ordered checklist of 3-6 execution steps"
    )


class PatchProposal(BaseModel):
    root_cause: str = Field(description="Root cause summary")
    file_path: str = Field(description="Relative path of the single file to change")
    updated_content: str = Field(description="Full updated file contents")
    commit_message: str = Field(description="Short conventional commit message")


class CritiqueResultModel(BaseModel):
    satisfactory: bool = Field(description="True only if patch matches the architecture plan")
    issues: list[str] = Field(
        description="Problems found; cite specific line numbers when rejecting"
    )
    revision_instructions: list[str] = Field(
        description="Concrete edit instructions for the developer agent"
    )


# ── Persona system prompts ──


def _persona_analyst() -> str:
    return """You are the Analyst Agent for Axolotl CI repair.
Extract a precise root cause from CI logs. Prefer ModuleNotFoundError / lint / format failures.
Be concise. Return only the requested structured fields."""


def _persona_architect() -> str:
    return """You are the Architect Agent for Axolotl CI repair.
Design a low-blast-radius, single-file fix strategy.
strategy_type must be one of: deps, lint, format, code_patch.
Prefer requirements.txt for missing modules; prefer minimal patches for lint/format.
List affected_files (usually one path). Return only the ArchitecturePlan fields."""


def _persona_tech_lead() -> str:
    return """You are the Tech Lead Agent for Axolotl CI repair.
Turn the ArchitecturePlan into an ordered, dependency-aware checklist (3-6 short steps).
Do not write code. Return only task_breakdown as a list of strings."""


def _persona_developer() -> str:
    return """You are the Developer Agent for Axolotl CI repair.
Produce a single-file patch (file_path, full updated_content, commit_message).
MVP rules:
1. ModuleNotFoundError → update requirements.txt
2. black/ruff format → apply formatting fix
3. lint/flake8/ruff → patch the affected file
When revising, PRESERVE successful work: apply targeted edits to the existing
updated_content using validation_failures and review revision_instructions.
Do not rewrite from scratch unless the prior content is empty or unusable."""


def _persona_evaluator() -> str:
    return """You are the Evaluator Agent for Axolotl CI repair.
Compare updated_content against root_cause and architecture_plan.
Approve only if the patch is minimal, correct, and matches the plan.
If rejecting: issues MUST cite specific line numbers in the updated content,
and revision_instructions must be concrete actionable edits.
Return CritiqueResult fields only."""


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("CI_FIX_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


def _flash_model() -> str:
    return (
        os.getenv("GEMINI_FLASH_MODEL")
        or os.getenv("GEMINI_MODEL")
        or "gemini-2.5-flash"
    )


def _pro_model() -> str:
    return (
        os.getenv("GEMINI_PRO_MODEL")
        or os.getenv("GEMINI_MODEL")
        or "gemini-2.5-pro"
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _plan_as_dict(plan: Any) -> ArchitecturePlan:
    if isinstance(plan, dict) and "strategy_type" in plan:
        return {
            "strategy_type": str(plan.get("strategy_type") or ""),
            "affected_files": list(plan.get("affected_files") or []),
            "proposed_solution": str(plan.get("proposed_solution") or ""),
        }
    return empty_architecture_plan()


class LangGraphCIFixAgent(BaseAgent):
    """Eight-stage CI fix via LangGraph with Flash/Pro personas and artifact contracts."""

    def __init__(self, on_stage: Optional[StageCallback] = None) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")

        self.on_stage = on_stage
        self.langsmith_enabled = configure_langsmith()
        self.validate_enabled = _env_bool("CI_FIX_VALIDATE", True)
        self.max_attempts = _max_attempts()
        self.flash_model = _flash_model()
        self.pro_model = _pro_model()
        self.llm_flash = ChatGoogleGenerativeAI(
            model=self.flash_model,
            google_api_key=api_key,
            temperature=0,
        )
        self.llm_pro = ChatGoogleGenerativeAI(
            model=self.pro_model,
            google_api_key=api_key,
            temperature=0,
        )
        self._graph = self._build_graph()

    def set_on_stage(self, on_stage: Optional[StageCallback]) -> None:
        self.on_stage = on_stage

    async def _emit(self, stage: str, message: str, metadata: Optional[dict] = None) -> None:
        if not self.on_stage:
            return
        result = self.on_stage(stage, message, metadata)
        if inspect.isawaitable(result):
            await result

    def _build_graph(self):
        workflow = StateGraph(CIFixState)
        workflow.add_node("workspace_setup", self._workspace_setup)
        workflow.add_node("requirements_analysis", self._requirements_analysis)
        workflow.add_node("technical_architecture", self._technical_architecture)
        workflow.add_node("task_breakdown", self._task_breakdown)
        workflow.add_node("code_implementation", self._code_implementation)
        workflow.add_node("testing_validation", self._testing_validation)
        workflow.add_node("code_review", self._code_review)

        workflow.add_edge(START, "workspace_setup")
        workflow.add_edge("workspace_setup", "requirements_analysis")
        workflow.add_edge("requirements_analysis", "technical_architecture")
        workflow.add_edge("technical_architecture", "task_breakdown")
        workflow.add_edge("task_breakdown", "code_implementation")
        workflow.add_edge("code_implementation", "testing_validation")
        workflow.add_conditional_edges(
            "testing_validation",
            self._route_after_testing,
            {
                "code_review": "code_review",
                "code_implementation": "code_implementation",
                "end": END,
            },
        )
        workflow.add_conditional_edges(
            "code_review",
            self._route_after_review,
            {
                "end": END,
                "code_implementation": "code_implementation",
            },
        )
        return workflow.compile()

    async def _workspace_setup(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "workspace_setup",
            f"Preparing sandbox workspace for pipeline {state['pipeline_id']}...",
            {"pipeline_id": state["pipeline_id"], "branch": state["branch"]},
        )
        reset_workspace(state["pipeline_id"])
        seed = (
            f"Workspace ready.\n"
            f"Project: {state['project_id']}\n"
            f"Pipeline: {state['pipeline_id']}\n"
            f"Branch: {state['branch']}"
        )
        return {
            "current_stage": "workspace_setup",
            "messages": [SystemMessage(content=seed)],
        }

    async def _requirements_analysis(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "requirements_analysis",
            "Analyst (Flash): extracting root cause from CI logs...",
            {"model": self.flash_model},
        )
        prompt = PromptBuilder.build_prompt(
            PipelineFailure(
                project_id=state["project_id"],
                pipeline_id=state["pipeline_id"],
                branch=state["branch"],
                logs=state["logs"],
            )
        )
        human = f"{prompt}\n\nRespond with JSON: {{\"root_cause\": \"...\"}}"
        structured = self.llm_flash.with_structured_output(DiagnosisResult)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_analyst()), HumanMessage(content=human)]
            )
            root_cause = result.root_cause if isinstance(result, DiagnosisResult) else str(result)
        except Exception:
            response = await self.llm_flash.ainvoke(
                [SystemMessage(content=_persona_analyst()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            root_cause = str(payload.get("root_cause", "Unknown CI failure"))

        await self._emit(
            "requirements_analysis",
            f"Root cause: {root_cause}",
            {"root_cause": root_cause},
        )
        return {
            "current_stage": "requirements_analysis",
            "root_cause": root_cause,
            "messages": [HumanMessage(content=human)],
        }

    async def _technical_architecture(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "technical_architecture",
            "Architect (Pro): designing low-blast-radius plan...",
            {"model": self.pro_model, "root_cause": state.get("root_cause")},
        )
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"Logs (excerpt):\n{(state.get('logs') or '')[:4000]}\n\n"
            "Produce an ArchitecturePlan JSON with strategy_type, affected_files, "
            "proposed_solution. Prefer a single-file fix."
        )
        structured = self.llm_pro.with_structured_output(ArchitecturePlanModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_architect()), HumanMessage(content=human)]
            )
            if isinstance(result, ArchitecturePlanModel):
                plan = result.model_dump()
            else:
                plan = ArchitecturePlanModel.model_validate(result).model_dump()
        except Exception:
            response = await self.llm_pro.ainvoke(
                [SystemMessage(content=_persona_architect()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            plan = {
                "strategy_type": str(payload.get("strategy_type") or "code_patch"),
                "affected_files": list(payload.get("affected_files") or []),
                "proposed_solution": str(
                    payload.get("proposed_solution") or "Apply a minimal single-file patch."
                ),
            }

        plan_td = _plan_as_dict(plan)
        await self._emit(
            "technical_architecture",
            f"Plan [{plan_td['strategy_type']}]: {plan_td['proposed_solution'][:280]}",
            {
                "strategy_type": plan_td["strategy_type"],
                "affected_files": plan_td["affected_files"],
            },
        )
        return {
            "current_stage": "technical_architecture",
            "architecture_plan": plan_td,
            "messages": [HumanMessage(content=human)],
        }

    async def _task_breakdown(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        await self._emit(
            "task_breakdown",
            "Tech Lead (Flash): breaking plan into tasks...",
            {"model": self.flash_model, "strategy_type": plan.get("strategy_type")},
        )
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"ArchitecturePlan: {json.dumps(plan)}\n\n"
            "Produce task_breakdown as an ordered list of 3-6 short strings."
        )
        structured = self.llm_flash.with_structured_output(TaskBreakdownResult)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_tech_lead()), HumanMessage(content=human)]
            )
            if isinstance(result, TaskBreakdownResult):
                tasks = list(result.task_breakdown)
            else:
                tasks = list(TaskBreakdownResult.model_validate(result).task_breakdown)
        except Exception:
            response = await self.llm_flash.ainvoke(
                [SystemMessage(content=_persona_tech_lead()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            raw = payload.get("task_breakdown")
            if isinstance(raw, list):
                tasks = [str(t) for t in raw]
            elif isinstance(raw, str):
                tasks = [line.strip(" -") for line in raw.splitlines() if line.strip()]
            else:
                tasks = [
                    "Edit the target file per architecture plan",
                    "Validate in Docker sandbox",
                    "Prepare commit message",
                ]

        await self._emit(
            "task_breakdown",
            "Tasks:\n" + "\n".join(f"- {t}" for t in tasks[:8]),
            {"task_breakdown": tasks[:12]},
        )
        return {
            "current_stage": "task_breakdown",
            "task_breakdown": tasks,
            "messages": [HumanMessage(content=human)],
        }

    async def _code_implementation(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        failures = list(state.get("validation_failures") or [])
        history = list(state.get("review_history") or [])
        is_revision = bool(failures or history) and bool(state.get("updated_content"))

        await self._emit(
            "code_implementation",
            (
                "Developer (Pro): applying targeted revision..."
                if is_revision
                else "Developer (Pro): implementing single-file fix..."
            ),
            {
                "model": self.pro_model,
                "attempt": int(state.get("attempts") or 0) + 1,
                "revision": is_revision,
                "strategy_type": plan.get("strategy_type"),
            },
        )

        tasks = state.get("task_breakdown") or []
        if is_revision:
            last_critique = history[-1] if history else None
            human = (
                f"TARGETED REVISION — preserve successful work in the existing file.\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"Current file_path: {state.get('file_path')}\n"
                f"Current updated_content:\n{state.get('updated_content')}\n"
                f"validation_failures: {json.dumps(failures[-3:])}\n"
                f"latest critique: {json.dumps(last_critique)}\n\n"
                "Apply only the revision_instructions / validation fixes. "
                "Return PatchProposal JSON (root_cause, file_path, updated_content, commit_message)."
            )
        else:
            human = (
                f"Project: {state['project_id']}\n"
                f"Pipeline: {state['pipeline_id']}\n"
                f"Branch: {state['branch']}\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"Logs:\n{state['logs']}\n\n"
                "Implement a single-file fix. Return PatchProposal JSON."
            )

        patch = await self._invoke_patch(state, human)
        await self._emit(
            "code_implementation",
            f"Proposed `{patch.get('file_path')}`: {patch.get('commit_message')}",
            {
                "file_path": patch.get("file_path"),
                "commit_message": patch.get("commit_message"),
                "strategy_type": plan.get("strategy_type"),
            },
        )
        return {
            "current_stage": "code_implementation",
            **patch,
            "review_approved": False,
        }

    async def _invoke_patch(self, state: CIFixState, human: str) -> dict[str, Any]:
        structured = self.llm_pro.with_structured_output(PatchProposal)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            if isinstance(result, PatchProposal):
                patch = result
            else:
                patch = PatchProposal.model_validate(result)
        except Exception:
            response = await self.llm_pro.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            patch = PatchProposal(
                root_cause=str(payload.get("root_cause", state.get("root_cause") or "AI fix")),
                file_path=str(payload.get("file_path", "")),
                updated_content=str(payload.get("updated_content", "")),
                commit_message=str(payload.get("commit_message", "fix: apply AI-generated patch")),
            )

        return {
            "root_cause": patch.root_cause,
            "file_path": patch.file_path,
            "updated_content": patch.updated_content,
            "commit_message": patch.commit_message,
            "messages": [HumanMessage(content=human)],
        }

    async def _testing_validation(self, state: CIFixState) -> dict[str, Any]:
        attempts = int(state.get("attempts") or 0) + 1
        failures = list(state.get("validation_failures") or [])
        await self._emit(
            "testing_validation",
            f"Validating patch in Docker sandbox (attempt {attempts})...",
            {"attempts": attempts, "file_path": state.get("file_path")},
        )

        file_path = state.get("file_path") or ""
        content = state.get("updated_content") or ""

        if not self.validate_enabled:
            output = "Validation skipped (CI_FIX_VALIDATE=false)."
            await self._emit("testing_validation", output, {"passed": True})
            return {
                "current_stage": "testing_validation",
                "attempts": attempts,
                "validation_passed": True,
                "validation_output": output,
                "validation_failures": failures,
            }

        if not file_path or not content:
            output = "Missing file_path or updated_content in proposal."
            failures = failures + [output]
            await self._emit("testing_validation", output, {"passed": False})
            return {
                "current_stage": "testing_validation",
                "attempts": attempts,
                "validation_passed": False,
                "validation_output": output,
                "validation_failures": failures,
            }

        result = validate_patch(
            pipeline_id=state["pipeline_id"],
            file_path=file_path,
            content=content,
            logs=state.get("logs") or "",
        )
        output = f"$ {result.command}\n{result.output}"
        if not result.passed:
            failures = failures + [output[:2000]]

        await self._emit(
            "testing_validation",
            f"Validation {'passed' if result.passed else 'failed'}: {result.output[:300]}",
            {"passed": result.passed, "output": output[:1000]},
        )
        return {
            "current_stage": "testing_validation",
            "attempts": attempts,
            "validation_passed": result.passed,
            "validation_output": output,
            "validation_failures": failures,
        }

    async def _code_review(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        history = list(state.get("review_history") or [])
        await self._emit(
            "code_review",
            "Evaluator (Pro): reviewing patch against architecture plan...",
            {"model": self.pro_model, "strategy_type": plan.get("strategy_type")},
        )
        # Number lines so the evaluator can cite them
        content = state.get("updated_content") or ""
        numbered = "\n".join(
            f"{i:4d}| {line}" for i, line in enumerate(content.splitlines(), start=1)
        )
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"ArchitecturePlan: {json.dumps(plan)}\n"
            f"File: {state.get('file_path')}\n"
            f"Commit message: {state.get('commit_message')}\n"
            f"Validation output:\n{state.get('validation_output')}\n"
            f"Updated content (line-numbered):\n{numbered}\n\n"
            "Return CritiqueResult. If unsatisfactory, issues must cite line numbers "
            "and revision_instructions must be concrete."
        )
        structured = self.llm_pro.with_structured_output(CritiqueResultModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_evaluator()), HumanMessage(content=human)]
            )
            if isinstance(result, CritiqueResultModel):
                critique = result.model_dump()
            else:
                critique = CritiqueResultModel.model_validate(result).model_dump()
        except Exception:
            response = await self.llm_pro.ainvoke(
                [SystemMessage(content=_persona_evaluator()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            critique = {
                "satisfactory": bool(payload.get("satisfactory", True)),
                "issues": list(payload.get("issues") or []),
                "revision_instructions": list(payload.get("revision_instructions") or []),
            }

        critique_td: CritiqueResult = {
            "satisfactory": bool(critique.get("satisfactory")),
            "issues": [str(i) for i in (critique.get("issues") or [])],
            "revision_instructions": [
                str(i) for i in (critique.get("revision_instructions") or [])
            ],
        }
        history = history + [critique_td]
        approved = critique_td["satisfactory"]

        summary = (
            "approved"
            if approved
            else "; ".join(critique_td["issues"][:3]) or "changes requested"
        )
        await self._emit(
            "code_review",
            f"Review {'approved' if approved else 'rejected'}: {summary[:300]}",
            {
                "review_approved": approved,
                "issues": critique_td["issues"][:5],
                "revision_instructions": critique_td["revision_instructions"][:5],
                "strategy_type": plan.get("strategy_type"),
            },
        )
        return {
            "current_stage": "code_review",
            "review_approved": approved,
            "review_history": history,
            "messages": [HumanMessage(content=human)],
        }

    def _route_after_testing(
        self, state: CIFixState
    ) -> Literal["code_review", "code_implementation", "end"]:
        if state.get("validation_passed"):
            return "code_review"
        if int(state.get("attempts") or 0) < self.max_attempts:
            return "code_implementation"
        return "end"

    def _route_after_review(
        self, state: CIFixState
    ) -> Literal["end", "code_implementation"]:
        if state.get("review_approved"):
            return "end"
        if int(state.get("attempts") or 0) < self.max_attempts:
            return "code_implementation"
        return "end"

    @override
    @traceable(name="ci_fix_analyze", run_type="chain")
    async def analyze(self, failure: PipelineFailure) -> FixProposal:
        """Run the eight-stage LangGraph CI fix loop and return a FixProposal."""
        print(
            f"[DEBUG] LangGraphCIFixAgent.analyze | project_id={failure.project_id} "
            f"| pipeline_id={failure.pipeline_id} | validate={self.validate_enabled} "
            f"| flash={self.flash_model} | pro={self.pro_model} "
            f"| langsmith={self.langsmith_enabled}"
        )
        initial: CIFixState = {
            "messages": [],
            "project_id": failure.project_id,
            "pipeline_id": failure.pipeline_id,
            "branch": failure.branch,
            "logs": failure.logs,
            "root_cause": "",
            "architecture_plan": empty_architecture_plan(),
            "task_breakdown": [],
            "file_path": "",
            "updated_content": "",
            "commit_message": "",
            "validation_output": "",
            "validation_passed": False,
            "validation_failures": [],
            "review_history": [],
            "review_approved": False,
            "attempts": 0,
            "current_stage": "",
        }

        run_config = build_run_config(
            pipeline_id=failure.pipeline_id,
            project_id=failure.project_id,
            branch=failure.branch,
            validate_enabled=self.validate_enabled,
        )
        run_config.setdefault("tags", [])
        run_config["tags"] = list(run_config["tags"]) + [
            "eight-stage",
            "artifact-contract",
            "workspace_setup",
            "requirements_analysis",
            "technical_architecture",
            "task_breakdown",
            "code_implementation",
            "testing_validation",
            "code_review",
        ]
        run_config.setdefault("metadata", {})
        run_config["metadata"] = {
            **dict(run_config["metadata"]),
            "flash_model": self.flash_model,
            "pro_model": self.pro_model,
        }

        try:
            final_state = await self._graph.ainvoke(initial, config=run_config)
        except Exception as exc:
            raise CIFixAgentError(f"CI fix analysis failed: {exc}") from exc
        finally:
            cleanup_workspace(failure.pipeline_id)

        validation_passed = bool(final_state.get("validation_passed"))
        review_approved = bool(final_state.get("review_approved"))
        attempts = int(final_state.get("attempts") or 0)
        validation_output = str(final_state.get("validation_output") or "")
        history = list(final_state.get("review_history") or [])

        if self.validate_enabled and not validation_passed:
            raise CIFixAgentError(
                f"Patch failed Docker validation after {attempts} attempt(s): {validation_output}"
            )
        if not review_approved:
            last = history[-1] if history else {}
            raise CIFixAgentError(
                f"Code review rejected after {attempts} attempt(s): "
                f"{last.get('issues') or last.get('revision_instructions') or 'no critique'}"
            )

        file_path = str(final_state.get("file_path") or "")
        updated_content = str(final_state.get("updated_content") or "")
        if not file_path or not updated_content:
            raise CIFixAgentError("LangGraph agent did not produce a usable patch")

        return FixProposal(
            root_cause=str(final_state.get("root_cause") or "AI-generated fix proposal."),
            file_path=file_path,
            updated_content=updated_content,
            commit_message=str(
                final_state.get("commit_message") or "fix: apply AI-generated patch"
            ),
            validation_passed=validation_passed if self.validate_enabled else None,
            validation_output=validation_output if self.validate_enabled else None,
            validation_attempts=attempts if self.validate_enabled else None,
        )
