"""
LangGraph CI fix agent — eight-stage Evaluator-Optimizer pipeline.

Artifact contracts (not chat transcripts) pass between persona nodes.
Supports multi-file patches and Knowledge Base graph grounding.

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
    FilePatch,
    empty_architecture_plan,
)
from agents.exceptions import CIFixAgentError
from agents.error_signature import (
    extract_error_signature,
    merge_affected_files,
    remaining_signature_hits,
)
from agents.knowledge_store import get_knowledge_store
from agents.langsmith_tracing import build_run_config, configure_langsmith
from agents.log_reducer import logs_for_llm, reduce_ci_logs
from agents.patch_utils import (
    DEFAULT_FUZZY_THRESHOLD,
    apply_blocks,
    apply_fuzzy_patch,
    build_block_failure_feedback,
    extract_line_hints,
    find_nearest_match,
    line_hint_for,
    normalize_patch_path,
)
from agents.prompt_builder import PromptBuilder
from agents.sandbox_tools import cleanup_workspace, reset_workspace, validate_patches
from schemas.fix import FilePatch as FixFilePatch
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure

load_dotenv()

StageCallback = Callable[[str, str, Optional[dict]], Awaitable[None] | None]


# ── Pydantic artifact mirrors ──


class DiagnosisResult(BaseModel):
    root_cause: str = Field(description="Concise root cause of the CI failure")


class ArchitecturePlanModel(BaseModel):
    strategy_type: str = Field(description="One of: deps, lint, format, code_patch")
    affected_files: list[str] = Field(
        description="All relative file paths that need edits"
    )
    proposed_solution: str = Field(description="Low-blast-radius solution summary")


class TaskBreakdownResult(BaseModel):
    task_breakdown: list[str] = Field(description="Ordered checklist of 3-6 steps")


class SearchReplaceBlockModel(BaseModel):
    """Aider-style code-surgery block (single-pass generation, TRD addendum)."""

    file_path: str = Field(description="Relative path of the file to change")
    search_block: str = Field(
        description=(
            "Lines copied CHARACTER-FOR-CHARACTER from the provided file contents "
            "(exact whitespace and indentation). Empty only when creating a new file."
        )
    )
    replace_block: str = Field(description="Replacement lines for the search_block")


class SearchReplaceProposal(BaseModel):
    root_cause: str = Field(description="Root cause summary")
    blocks: list[SearchReplaceBlockModel] = Field(
        description="Ordered SEARCH/REPLACE blocks; multiple blocks per file allowed"
    )
    commit_message: str = Field(description="Short conventional commit message")


class CritiqueResultModel(BaseModel):
    satisfactory: bool = Field(description="True only if patches match the architecture plan")
    issues: list[str] = Field(
        description="Problems found; cite file paths and line numbers when rejecting"
    )
    revision_instructions: list[str] = Field(
        description="Concrete edit instructions for the developer agent"
    )


# ── Personas ──


def _persona_analyst() -> str:
    return """You are the Analyst Agent for Axolotl CI repair.
Extract a precise root cause from CI logs. Prefer ModuleNotFoundError / lint / format failures.
If historical KB context is provided, use it to refine the diagnosis when it clearly matches.
Be concise. Return only the requested structured fields."""


def _persona_architect() -> str:
    return """You are the Architect Agent for Axolotl CI repair.
Design a low-blast-radius fix. strategy_type must be one of: deps, lint, format, code_patch.
List ALL affected_files that need modification (multi-file allowed when necessary).
Prefer requirements.txt for missing modules.
IMPORTANT: CI logs are often fail-fast and may only name ONE broken file. Still list every
file you can infer from the logs/stack traces. A later error_expansion stage will search
the repo for siblings with the same signature and enlarge this list.
Return ArchitecturePlan fields only."""


def _persona_tech_lead() -> str:
    return """You are the Tech Lead Agent for Axolotl CI repair.
Turn the ArchitecturePlan into an ordered, dependency-aware checklist (3-6 short steps).
If expanded_files lists siblings beyond the seed failure, include a step to fix ALL of them
in the same change set. Do not write code. Return only task_breakdown as a list of strings."""


def _persona_developer() -> str:
    return """You are the Developer Agent for Axolotl CI repair — a precise code surgeon.
You fix code by emitting SEARCH/REPLACE blocks, never whole files.
Strict rules:
1. search_block must be copied CHARACTER-FOR-CHARACTER from the provided file contents:
   exact whitespace, exact indentation, exact blank lines. Never retype from memory.
2. Keep each block minimal — only the lines that change plus 1-2 unchanged anchor lines.
3. Multiple blocks per file are allowed; they apply top to bottom.
4. To create a NEW file, use an empty search_block and put the full contents in replace_block.
5. Never put line-number prefixes or markdown fences inside blocks.
6. If multiple files share the SAME error signature, emit blocks for EVERY listed file —
   do not stop after fixing the seed file from the CI log.
Fix guidance:
- ModuleNotFoundError → add the dependency to requirements.txt (imports only if required)
- black/ruff format or lint errors → patch only the offending lines
When revising, PRESERVE successful work: emit blocks only for what must still change,
guided by validation_failures and review revision_instructions."""


def _persona_evaluator() -> str:
    return """You are the Evaluator Agent for Axolotl CI repair.
Your job is to review ONLY the changes the Developer Agent made — NOT pre-existing code quality.

Approval criteria (ALL must be true):
1. The patch correctly addresses the diagnosed root cause.
2. The patch matches the architecture plan's strategy and affected files.
3. The patch does not introduce NEW bugs, syntax errors, or regressions.
4. The patch is minimal — it changes only what is necessary to fix the CI failure.

You MUST IGNORE:
- Pre-existing unused imports, PEP8 issues, or code style problems that were
  already present in the ORIGINAL file BEFORE the developer's patch.
- Functions, classes, or logic that the developer did NOT touch.
- Any issue visible in the original file diff context marked as ORIGINAL.

A DIFF section is provided showing exactly what lines were added/removed.
Only evaluate those changes. If the diff correctly fixes the root cause
without introducing new problems, mark satisfactory=true.

If rejecting: issues MUST cite file paths and line numbers of NEWLY
introduced problems, and revision_instructions must be concrete actionable edits.
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
    return os.getenv("GEMINI_FLASH_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"


def _pro_model() -> str:
    return os.getenv("GEMINI_PRO_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-pro"


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


def _normalize_patches(raw: Any) -> list[FilePatch]:
    patches: list[FilePatch] = []
    if not raw:
        return patches
    for item in raw:
        if isinstance(item, dict):
            path = str(item.get("file_path") or "")
            content = str(item.get("updated_content") or "")
        else:
            path = str(getattr(item, "file_path", "") or "")
            content = str(getattr(item, "updated_content", "") or "")
        if path:
            patches.append({"file_path": path, "updated_content": content})
    return patches


class LangGraphCIFixAgent(BaseAgent):
    """Eight-stage CI fix with Flash/Pro personas, multi-file patches, and KB grounding."""

    def __init__(self, on_stage: Optional[StageCallback] = None) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")

        self.on_stage = on_stage
        self.file_fetcher: Optional[Callable[[str], Awaitable[Optional[str]] | Optional[str]]] = None
        self.code_searcher: Optional[
            Callable[[list[str]], Awaitable[list[str]] | list[str]]
        ] = None
        self.langsmith_enabled = configure_langsmith()
        self.validate_enabled = _env_bool("CI_FIX_VALIDATE", True)
        self.max_attempts = _max_attempts()
        try:
            self.block_retries = max(0, int(os.getenv("CI_FIX_BLOCK_RETRIES", "2")))
        except ValueError:
            self.block_retries = 2
        try:
            self.fuzzy_threshold = float(
                os.getenv("CI_FIX_FUZZY_THRESHOLD", str(DEFAULT_FUZZY_THRESHOLD))
            )
        except ValueError:
            self.fuzzy_threshold = DEFAULT_FUZZY_THRESHOLD
        try:
            self.expansion_max_files = max(
                1, int(os.getenv("CI_FIX_EXPANSION_MAX_FILES", "25"))
            )
        except ValueError:
            self.expansion_max_files = 25
        self.flash_model = _flash_model()
        self.pro_model = _pro_model()
        self.llm_flash = ChatGoogleGenerativeAI(
            model=self.flash_model, google_api_key=api_key, temperature=0
        )
        self.llm_pro = ChatGoogleGenerativeAI(
            model=self.pro_model, google_api_key=api_key, temperature=0
        )
        self._graph = self._build_graph()

    def set_on_stage(self, on_stage: Optional[StageCallback]) -> None:
        self.on_stage = on_stage

    def set_file_fetcher(self, fetcher) -> None:
        """Attach a callable(file_path) -> str|None that reads repo files (MCP-backed)."""
        self.file_fetcher = fetcher

    def set_code_searcher(self, searcher) -> None:
        """Attach a callable(patterns) -> list[file_path] for same-error fan-out."""
        self.code_searcher = searcher

    async def _fetch_original(self, file_path: str) -> Optional[str]:
        """Fetch original repo contents for a file; None when missing/unavailable."""
        if self.file_fetcher is None:
            return None
        try:
            result = self.file_fetcher(file_path)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, str) else None
        except Exception as exc:
            print(f"[PatchEngine] Failed to fetch {file_path}: {exc}")
            return None

    async def _search_siblings(self, patterns: list[str]) -> list[str]:
        """Run the injected repo searcher; empty when unavailable."""
        if self.code_searcher is None or not patterns:
            return []
        try:
            result = self.code_searcher(patterns)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return []
            return [normalize_patch_path(str(p)) for p in result if p]
        except Exception as exc:
            print(f"[ErrorExpansion] Repo search failed: {exc}")
            return []

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
        workflow.add_node("error_expansion", self._error_expansion)
        workflow.add_node("task_breakdown", self._task_breakdown)
        workflow.add_node("code_implementation", self._code_implementation)
        workflow.add_node("testing_validation", self._testing_validation)
        workflow.add_node("code_review", self._code_review)

        workflow.add_edge(START, "workspace_setup")
        workflow.add_edge("workspace_setup", "requirements_analysis")
        workflow.add_edge("requirements_analysis", "technical_architecture")
        workflow.add_edge("technical_architecture", "error_expansion")
        workflow.add_edge("error_expansion", "task_breakdown")
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
            {"end": END, "code_implementation": "code_implementation"},
        )
        return workflow.compile()

    async def _workspace_setup(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "workspace_setup",
            f"Preparing sandbox workspace for pipeline {state['pipeline_id']}...",
            {"pipeline_id": state["pipeline_id"], "branch": state["branch"]},
        )
        reset_workspace(state["pipeline_id"])

        # Compress CI logs once up front — LLMs see the digest; regex tools keep raw.
        reduced = reduce_ci_logs(state.get("logs") or "")
        digest = str(reduced.get("digest") or "")
        relevant = list(reduced.get("relevant_errors") or [])
        ratio = float(reduced.get("compression_ratio") or 1.0)
        await self._emit(
            "workspace_setup",
            (
                f"CI log digest ready: {reduced.get('raw_chars', 0)} → "
                f"{reduced.get('digest_chars', 0)} chars "
                f"({ratio:.0%} kept, {len(relevant)} error block(s), "
                f"strategy={reduced.get('strategy')})"
            ),
            {
                "raw_chars": reduced.get("raw_chars"),
                "digest_chars": reduced.get("digest_chars"),
                "compression_ratio": ratio,
                "relevant_error_count": len(relevant),
                "strategy": reduced.get("strategy"),
            },
        )

        seed = (
            f"Workspace ready.\nProject: {state['project_id']}\n"
            f"Pipeline: {state['pipeline_id']}\nBranch: {state['branch']}\n"
            f"Log digest: {reduced.get('digest_chars', 0)} chars "
            f"(from {reduced.get('raw_chars', 0)} raw)"
        )
        return {
            "current_stage": "workspace_setup",
            "logs_digest": digest,
            "relevant_errors": relevant,
            "messages": [SystemMessage(content=seed)],
        }

    async def _requirements_analysis(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "requirements_analysis",
            "Analyst (Flash): KB grounding + root-cause extraction...",
            {"model": self.flash_model},
        )

        kb_grounding = ""
        digest = logs_for_llm(state)
        try:
            store = get_knowledge_store()
            historical = await store.find_historical_fixes(
                project_id=state["project_id"],
                error_text=digest or (state.get("logs") or ""),
                limit=3,
            )
            if historical:
                lines = []
                for h in historical:
                    lines.append(
                        f"- Claim: {h.get('claim_label')}\n"
                        f"  Prior fix: {h.get('artifact_summary')}\n"
                        f"  Commit: {h.get('commit_message')}\n"
                        f"  Patches: {json.dumps(h.get('artifact_patches') or [])[:800]}"
                    )
                kb_grounding = "Historical KB matches:\n" + "\n".join(lines)
                await self._emit(
                    "requirements_analysis",
                    f"KB grounding: {len(historical)} historical claim(s) found",
                    {"kb_hits": len(historical)},
                )
        except Exception as exc:
            print(f"[KB] grounding lookup failed: {exc}")
            kb_grounding = ""

        prompt = PromptBuilder.build_prompt(
            PipelineFailure(
                project_id=state["project_id"],
                pipeline_id=state["pipeline_id"],
                branch=state["branch"],
                logs=digest,
            ),
            logs=digest,
        )
        human = (
            f"{prompt}\n\n"
            f"{kb_grounding}\n\n"
            'Respond with JSON: {"root_cause": "..."}'
        )
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

        # Line hints for the middle-out patch search (regex over stack traces; no LLM cost)
        line_hints = extract_line_hints(state.get("logs") or "")
        if line_hints:
            await self._emit(
                "requirements_analysis",
                f"Line hints from stack trace: {json.dumps(line_hints)[:300]}",
                {"line_hints": line_hints},
            )

        await self._emit(
            "requirements_analysis",
            f"Root cause: {root_cause}",
            {"root_cause": root_cause},
        )
        return {
            "current_stage": "requirements_analysis",
            "root_cause": root_cause,
            "line_hints": line_hints,
            "kb_grounding": kb_grounding,
            "messages": [HumanMessage(content=human)],
        }

    async def _technical_architecture(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "technical_architecture",
            "Architect (Pro): designing multi-file plan...",
            {"model": self.pro_model},
        )
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"KB grounding:\n{state.get('kb_grounding') or '(none)'}\n"
            f"Relevant CI errors (digest):\n{logs_for_llm(state)}\n\n"
            "Produce ArchitecturePlan JSON. List every affected file."
        )
        structured = self.llm_pro.with_structured_output(ArchitecturePlanModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_architect()), HumanMessage(content=human)]
            )
            plan = (
                result.model_dump()
                if isinstance(result, ArchitecturePlanModel)
                else ArchitecturePlanModel.model_validate(result).model_dump()
            )
        except Exception:
            response = await self.llm_pro.ainvoke(
                [SystemMessage(content=_persona_architect()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            plan = {
                "strategy_type": str(payload.get("strategy_type") or "code_patch"),
                "affected_files": list(payload.get("affected_files") or []),
                "proposed_solution": str(
                    payload.get("proposed_solution") or "Apply a minimal patch set."
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

    async def _error_expansion(self, state: CIFixState) -> dict[str, Any]:
        """Fan out from the CI seed error to sibling files with the same signature."""
        plan = _plan_as_dict(state.get("architecture_plan"))
        hints = dict(state.get("line_hints") or {})
        signature = extract_error_signature(
            state.get("logs") or "",
            root_cause=str(state.get("root_cause") or ""),
            line_hints=hints,
        )
        patterns = list(signature.get("patterns") or [])

        await self._emit(
            "error_expansion",
            (
                f"Expanding error signature [{signature.get('error_class')}] "
                f"across the repository ({len(patterns)} pattern(s))..."
            ),
            {
                "error_class": signature.get("error_class"),
                "patterns": patterns[:8],
                "seed_files": signature.get("seed_files") or [],
            },
        )

        discovered = await self._search_siblings(patterns)
        # Also include seed files from stack traces even if search is empty
        discovered = list(
            dict.fromkeys(
                [normalize_patch_path(p) for p in (signature.get("seed_files") or [])]
                + discovered
            )
        )

        # Local content scan fallback: if searcher returned nothing but we already
        # fetched some files, still keep planned + seed paths.
        expanded = merge_affected_files(
            list(plan.get("affected_files") or []),
            discovered,
            error_class=str(signature.get("error_class") or "unknown"),
            max_files=self.expansion_max_files,
        )

        # Prefer deps file presence for ModuleNotFound even when not in plan
        if signature.get("error_class") == "deps":
            for dep_path in ("requirements.txt", "pyproject.toml"):
                if dep_path not in expanded:
                    content = await self._fetch_original(dep_path)
                    if content is not None:
                        expanded = merge_affected_files(
                            expanded,
                            [dep_path],
                            error_class="deps",
                            max_files=self.expansion_max_files,
                        )

        plan = {
            **plan,
            "affected_files": expanded,
            "proposed_solution": (
                f"{plan.get('proposed_solution') or ''} "
                f"(expanded to {len(expanded)} file(s) via same-error fan-out)"
            ).strip(),
        }

        new_siblings = [
            p for p in expanded if p not in (signature.get("seed_files") or [])
            and p not in (state.get("architecture_plan") or {}).get("affected_files", [])
        ]
        await self._emit(
            "error_expansion",
            (
                f"Worklist: {len(expanded)} file(s)"
                + (f" (+{len(new_siblings)} sibling hit(s) beyond the seed)" if new_siblings else "")
                + f": {', '.join(expanded[:8])}"
            ),
            {
                "expanded_files": expanded,
                "discovered": discovered[:20],
                "new_siblings": new_siblings[:20],
                "error_signature": signature,
            },
        )
        return {
            "current_stage": "error_expansion",
            "error_signature": signature,
            "expanded_files": expanded,
            "architecture_plan": plan,
        }

    async def _task_breakdown(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        expanded = list(state.get("expanded_files") or plan.get("affected_files") or [])
        await self._emit(
            "task_breakdown",
            "Tech Lead (Flash): breaking plan into tasks...",
            {"model": self.flash_model},
        )
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"ArchitecturePlan: {json.dumps(plan)}\n"
            f"Expanded files (seed + same-error siblings): {json.dumps(expanded)}\n"
            f"Error signature: {json.dumps(state.get('error_signature') or {})}\n\n"
            "Produce task_breakdown as an ordered list of 3-6 short strings. "
            "Include fixing EVERY expanded file when they share the same error."
        )
        structured = self.llm_flash.with_structured_output(TaskBreakdownResult)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_tech_lead()), HumanMessage(content=human)]
            )
            tasks = list(
                result.task_breakdown
                if isinstance(result, TaskBreakdownResult)
                else TaskBreakdownResult.model_validate(result).task_breakdown
            )
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
                    "Edit listed affected files",
                    "Validate all patches in sandbox",
                    "Prepare single commit message",
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

    # ── Stage 5: single-pass Search/Replace code surgery ──

    _FILE_CONTEXT_CHAR_CAP = 24000
    _HINT_WINDOW_LINES = 120

    def _file_context_section(
        self, path: str, content: Optional[str], hint: Optional[int]
    ) -> str:
        """One file's contents for the developer prompt (hint-windowed if huge)."""
        if content is None:
            return f"### {path} (NEW FILE — does not exist yet; create it with an empty search_block)"
        if len(content) <= self._FILE_CONTEXT_CHAR_CAP:
            return f"### {path}\n{content}"
        lines = content.splitlines()
        center = (hint - 1) if hint else len(lines) // 2
        lo = max(0, center - self._HINT_WINDOW_LINES)
        hi = min(len(lines), center + self._HINT_WINDOW_LINES)
        head = "\n".join(lines[:30])
        window = "\n".join(lines[lo:hi])
        return (
            f"### {path} (PARTIAL VIEW — file has {len(lines)} lines; "
            f"showing the head and lines {lo + 1}-{hi} around the failure)\n"
            f"{head}\n... (lines omitted) ...\n{window}\n... (lines omitted) ..."
        )

    async def _code_implementation(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        failures = list(state.get("validation_failures") or [])
        history = list(state.get("review_history") or [])
        existing = _normalize_patches(state.get("file_patches"))
        is_revision = bool(failures or history) and bool(existing)
        hints = dict(state.get("line_hints") or {})
        baseline: dict[str, Optional[str]] = dict(state.get("file_contents") or {})

        await self._emit(
            "code_implementation",
            (
                "Developer (Pro): targeted SEARCH/REPLACE revision..."
                if is_revision
                else "Developer (Pro): generating SEARCH/REPLACE blocks (single pass)..."
            ),
            {
                "model": self.pro_model,
                "attempt": int(state.get("attempts") or 0) + 1,
                "revision": is_revision,
                "affected_files": plan.get("affected_files"),
            },
        )

        # ── Gather real file contents (originals via MCP-backed fetcher) ──
        expanded = [
            normalize_patch_path(p)
            for p in (state.get("expanded_files") or plan.get("affected_files") or [])
            if p
        ]
        target_files = list(
            dict.fromkeys(
                [normalize_patch_path(p["file_path"]) for p in existing]
                + expanded
                + [normalize_patch_path(f) for f in (plan.get("affected_files") or [])]
            )
        )
        for path in target_files:
            if path not in baseline:
                baseline[path] = await self._fetch_original(path)

        patched_now = {normalize_patch_path(p["file_path"]): p["updated_content"] for p in existing}
        working: dict[str, str] = {}
        for path in target_files:
            if is_revision and path in patched_now:
                working[path] = patched_now[path]
            else:
                working[path] = baseline.get(path) or ""

        sections = []
        for path in target_files:
            shown = working[path] if (is_revision and path in patched_now) else baseline.get(path)
            sections.append(
                self._file_context_section(path, shown, line_hint_for(hints, path))
            )
        files_context = "\n\n".join(sections) or "(no file contents available)"

        tasks = state.get("task_breakdown") or []
        signature = state.get("error_signature") or {}
        if is_revision:
            last_critique = history[-1] if history else None
            human = (
                "TARGETED REVISION — emit SEARCH/REPLACE blocks ONLY for what must still change.\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Expanded files: {json.dumps(expanded)}\n"
                f"Error signature: {json.dumps(signature)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"validation_failures: {json.dumps(failures[-3:])}\n"
                f"patch apply failures: {json.dumps(list(state.get('patch_failures') or [])[-3:])}\n"
                f"latest critique: {json.dumps(last_critique)}\n\n"
                "CURRENT FILE CONTENTS (your prior patches are already applied — "
                "search blocks must match THIS text exactly):\n"
                f"{files_context}\n\n"
                "Return SearchReplaceProposal JSON: blocks + commit_message. "
                "Cover every expanded sibling that still has the error."
            )
        else:
            human = (
                f"Project: {state['project_id']}\n"
                f"Pipeline: {state['pipeline_id']}\n"
                f"Branch: {state['branch']}\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"KB grounding:\n{state.get('kb_grounding') or '(none)'}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Expanded files (fix ALL of these if they share the error): {json.dumps(expanded)}\n"
                f"Error signature: {json.dumps(signature)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"Failure line hints: {json.dumps(hints) or '(none)'}\n"
                f"Relevant CI errors (digest):\n{logs_for_llm(state)}\n\n"
                "FILE CONTENTS (search blocks must match this text exactly):\n"
                f"{files_context}\n\n"
                "Return SearchReplaceProposal JSON: blocks + commit_message. "
                "Emit blocks for every expanded file that contains the error signature."
            )

        proposal = await self._invoke_search_replace(state, human)
        blocks = proposal["blocks"]

        # ── Apply the blocks through the fuzzy patch engine ──
        outcome = apply_blocks(blocks, working, hints, self.fuzzy_threshold)

        # ── Rich diagnostic feedback loop: retry ONLY failed blocks ──
        patch_failures: list[str] = []
        for failed_block, diagnostics in outcome.failed:
            path = normalize_patch_path(str(failed_block.get("file_path") or ""))
            fixed = False
            for _ in range(self.block_retries):
                current = outcome.contents.get(path, "")
                nearest = find_nearest_match(
                    current, str(failed_block.get("search_block") or ""), context=12
                )
                feedback = build_block_failure_feedback(
                    file_path=path,
                    error=diagnostics.error,
                    nearest_match=nearest,
                    applied_count=len(outcome.applied),
                    total_count=len(blocks),
                )
                await self._emit(
                    "code_implementation",
                    f"Block failed in {path}; requesting targeted fix (cached "
                    f"{len(outcome.applied)}/{len(blocks)} applied blocks)...",
                    {"file": path, "error": diagnostics.error[:300]},
                )
                candidate = await self._invoke_block_fix(failed_block, feedback)
                if candidate is None:
                    continue
                retry = apply_fuzzy_patch(
                    current,
                    candidate.get("search_block") or "",
                    candidate.get("replace_block") or "",
                    line_hint=line_hint_for(hints, path),
                    threshold=self.fuzzy_threshold,
                )
                if retry.success:
                    outcome.contents[path] = retry.content
                    outcome.applied.append(candidate)
                    fixed = True
                    break
                diagnostics = retry
                failed_block = candidate
            if not fixed:
                patch_failures.append(f"{path}: {diagnostics.error}")

        # ── Collect changed files as full-content patches for downstream stages ──
        patches: list[FilePatch] = [
            {"file_path": path, "updated_content": content}
            for path, content in outcome.contents.items()
            if content != (baseline.get(path) or "")
        ]

        paths = [p["file_path"] for p in patches]
        await self._emit(
            "code_implementation",
            (
                f"Applied {len(outcome.applied)}/{len(blocks)} block(s) across "
                f"{len(paths)} file(s): {', '.join(paths[:5])} — {proposal['commit_message']}"
                + (f" | {len(patch_failures)} block(s) unresolved" if patch_failures else "")
            ),
            {
                "files": paths,
                "blocks_applied": len(outcome.applied),
                "blocks_total": len(blocks),
                "patch_failures": patch_failures[:5],
                "commit_message": proposal["commit_message"],
            },
        )
        return {
            "current_stage": "code_implementation",
            "root_cause": proposal["root_cause"],
            "file_patches": patches,
            "commit_message": proposal["commit_message"],
            "search_replace_blocks": [
                {
                    "file_path": str(b.get("file_path") or ""),
                    "search_block": str(b.get("search_block") or ""),
                    "replace_block": str(b.get("replace_block") or ""),
                }
                for b in outcome.applied
            ],
            "patch_failures": patch_failures,
            "file_contents": {k: v for k, v in baseline.items() if v is not None},
            "review_approved": False,
            "messages": [HumanMessage(content=human)],
        }

    async def _invoke_search_replace(self, state: CIFixState, human: str) -> dict[str, Any]:
        """Single-pass generation of SEARCH/REPLACE blocks (Gemini Pro)."""
        structured = self.llm_pro.with_structured_output(SearchReplaceProposal)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            proposal = (
                result
                if isinstance(result, SearchReplaceProposal)
                else SearchReplaceProposal.model_validate(result)
            )
            blocks = [b.model_dump() for b in proposal.blocks]
            root_cause = proposal.root_cause
            commit_message = proposal.commit_message
        except Exception:
            response = await self.llm_pro.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            payload = _extract_json_object(getattr(response, "content", "") or "")
            raw_blocks = payload.get("blocks") or payload.get("search_replace_blocks") or []
            blocks = [
                {
                    "file_path": str(b.get("file_path", "")),
                    "search_block": str(b.get("search_block", "")),
                    "replace_block": str(b.get("replace_block", "")),
                }
                for b in raw_blocks
                if isinstance(b, dict)
            ]
            root_cause = str(payload.get("root_cause", state.get("root_cause") or "AI fix"))
            commit_message = str(
                payload.get("commit_message", "fix: apply AI-generated patch")
            )

        return {
            "blocks": [b for b in blocks if str(b.get("file_path") or "").strip()],
            "root_cause": root_cause,
            "commit_message": commit_message,
        }

    async def _invoke_block_fix(
        self, failed_block: dict[str, str], feedback: str
    ) -> Optional[dict[str, str]]:
        """Ask the developer to fix ONLY the failed block (partial retry, TRD C)."""
        human = (
            f"{feedback}\n\n"
            f"The failed block was:\n{json.dumps(failed_block)[:4000]}\n\n"
            "Return a single SearchReplaceBlock JSON object: "
            '{"file_path": "...", "search_block": "...", "replace_block": "..."}'
        )
        structured = self.llm_pro.with_structured_output(SearchReplaceBlockModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            block = (
                result
                if isinstance(result, SearchReplaceBlockModel)
                else SearchReplaceBlockModel.model_validate(result)
            )
            return block.model_dump()
        except Exception:
            try:
                response = await self.llm_pro.ainvoke(
                    [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
                )
                payload = _extract_json_object(getattr(response, "content", "") or "")
                if payload.get("search_block") is not None:
                    return {
                        "file_path": str(
                            payload.get("file_path", failed_block.get("file_path", ""))
                        ),
                        "search_block": str(payload.get("search_block", "")),
                        "replace_block": str(payload.get("replace_block", "")),
                    }
            except Exception as exc:
                print(f"[PatchEngine] Block-fix retry failed: {exc}")
        return None

    async def _testing_validation(self, state: CIFixState) -> dict[str, Any]:
        attempts = int(state.get("attempts") or 0) + 1
        failures = list(state.get("validation_failures") or [])
        patches = _normalize_patches(state.get("file_patches"))
        signature = dict(state.get("error_signature") or {})
        expanded = [
            normalize_patch_path(p)
            for p in (state.get("expanded_files") or [])
            if p
        ]
        await self._emit(
            "testing_validation",
            f"Validating {len(patches)} patch(es) in Docker (attempt {attempts})...",
            {"attempts": attempts, "files": [p["file_path"] for p in patches]},
        )

        # Same-error leftover scan: patched + unpatched expanded siblings
        from agents.error_signature import actionable_cleanup_patterns

        cleanup_patterns = actionable_cleanup_patterns(signature)  # type: ignore[arg-type]
        patched_map = {
            normalize_patch_path(p["file_path"]): p["updated_content"] for p in patches
        }
        baseline = dict(state.get("file_contents") or {})
        scan_contents: dict[str, str] = {}
        for path in expanded or list(patched_map.keys()):
            if path in patched_map:
                scan_contents[path] = patched_map[path]
            elif path in baseline:
                scan_contents[path] = str(baseline[path])
            else:
                fetched = await self._fetch_original(path)
                if fetched is not None:
                    scan_contents[path] = fetched

        leftovers = remaining_signature_hits(
            scan_contents,
            cleanup_patterns,
            patched_paths=set(patched_map.keys()),
        )
        # Only fail the loop for leftovers that still contain the bad seed and
        # either were not patched or were patched incompletely.
        leftover_msg = ""
        if leftovers and cleanup_patterns:
            details = "; ".join(
                f"{item['file_path']} still has {item['patterns'][:2]}"
                for item in leftovers[:8]
            )
            leftover_msg = (
                "Same-error siblings still match the failure signature after this "
                f"patch set: {details}. Emit SEARCH/REPLACE blocks for EVERY listed file."
            )

        if not self.validate_enabled:
            if leftover_msg:
                failures = failures + [leftover_msg]
                await self._emit(
                    "testing_validation",
                    leftover_msg[:400],
                    {"passed": False, "leftovers": leftovers[:10]},
                )
                return {
                    "current_stage": "testing_validation",
                    "attempts": attempts,
                    "validation_passed": False,
                    "validation_output": leftover_msg,
                    "validation_failures": failures,
                }
            output = "Validation skipped (CI_FIX_VALIDATE=false)."
            await self._emit("testing_validation", output, {"passed": True})
            return {
                "current_stage": "testing_validation",
                "attempts": attempts,
                "validation_passed": True,
                "validation_output": output,
                "validation_failures": failures,
            }

        if not patches:
            output = leftover_msg or "No file_patches in proposal."
            failures = failures + [output]
            await self._emit("testing_validation", output, {"passed": False})
            return {
                "current_stage": "testing_validation",
                "attempts": attempts,
                "validation_passed": False,
                "validation_output": output,
                "validation_failures": failures,
            }

        result = validate_patches(
            pipeline_id=state["pipeline_id"],
            file_patches=patches,
            logs=state.get("logs") or "",
        )
        output = f"$ {result.command}\n{result.output}"
        passed = result.passed
        if not result.passed:
            failures = failures + [output[:2000]]
        if leftover_msg:
            passed = False
            failures = failures + [leftover_msg]
            output = f"{output}\n\n{leftover_msg}"

        await self._emit(
            "testing_validation",
            f"Validation {'passed' if passed else 'failed'}: {(leftover_msg or result.output)[:300]}",
            {
                "passed": passed,
                "output": output[:1000],
                "leftovers": leftovers[:10],
            },
        )
        return {
            "current_stage": "testing_validation",
            "attempts": attempts,
            "validation_passed": passed,
            "validation_output": output,
            "validation_failures": failures,
        }

    @staticmethod
    def _build_diff_summary(
        file_path: str, original: str | None, patched: str
    ) -> str:
        """Build a unified-diff-style summary showing what the developer changed."""
        import difflib

        orig_lines = (original or "").splitlines(keepends=True)
        patched_lines = patched.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines,
            patched_lines,
            fromfile=f"ORIGINAL {file_path}",
            tofile=f"PATCHED  {file_path}",
            lineterm="",
        )
        diff_text = "\n".join(diff)
        if not diff_text.strip():
            return f"### {file_path}\n(no changes)"
        return f"### {file_path}\n```diff\n{diff_text}\n```"

    async def _code_review(self, state: CIFixState) -> dict[str, Any]:
        plan = _plan_as_dict(state.get("architecture_plan"))
        history = list(state.get("review_history") or [])
        patches = _normalize_patches(state.get("file_patches"))
        originals: dict[str, str | None] = dict(state.get("file_contents") or {})
        await self._emit(
            "code_review",
            "Evaluator (Pro): reviewing multi-file patches...",
            {"model": self.pro_model, "files": [p["file_path"] for p in patches]},
        )

        # Build diff summaries showing exactly what the developer changed
        diff_sections = []
        for patch in patches:
            path = patch["file_path"]
            original = originals.get(path)
            diff_sections.append(
                self._build_diff_summary(path, original, patch["updated_content"])
            )

        # Also include numbered patched files for full context
        numbered_blocks = []
        for patch in patches:
            lines = patch["updated_content"].splitlines()
            numbered = "\n".join(
                f"{i:4d}| {line}" for i, line in enumerate(lines, start=1)
            )
            numbered_blocks.append(f"### {patch['file_path']}\n{numbered}")

        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"ArchitecturePlan: {json.dumps(plan)}\n"
            f"Commit message: {state.get('commit_message')}\n"
            f"Validation output:\n{state.get('validation_output')}\n"
            f"Unresolved patch-apply failures: {json.dumps(list(state.get('patch_failures') or []))}\n\n"
            "═══ DIFF (what the developer ACTUALLY changed) ═══\n"
            + "\n\n".join(diff_sections)
            + "\n\n═══ FULL PATCHED FILES (for reference) ═══\n"
            + "\n\n".join(numbered_blocks)
            + "\n\n"
            "IMPORTANT: Review ONLY the changes shown in the DIFF section above.\n"
            "Do NOT reject for pre-existing issues (unused imports, PEP8 style, "
            "unrelated functions) that appear in the ORIGINAL file and were NOT "
            "introduced by the developer's patch.\n"
            "Approve if the diff correctly fixes the root cause without introducing "
            "new bugs. Return CritiqueResult."
        )
        structured = self.llm_pro.with_structured_output(CritiqueResultModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_evaluator()), HumanMessage(content=human)]
            )
            critique = (
                result.model_dump()
                if isinstance(result, CritiqueResultModel)
                else CritiqueResultModel.model_validate(result).model_dump()
            )
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
        print(
            f"[DEBUG] LangGraphCIFixAgent.analyze | project_id={failure.project_id} "
            f"| pipeline_id={failure.pipeline_id} | validate={self.validate_enabled} "
            f"| flash={self.flash_model} | pro={self.pro_model}"
        )
        initial: CIFixState = {
            "messages": [],
            "project_id": failure.project_id,
            "pipeline_id": failure.pipeline_id,
            "branch": failure.branch,
            "logs": failure.logs,
            "logs_digest": "",
            "relevant_errors": [],
            "root_cause": "",
            "line_hints": {},
            "error_signature": {},
            "architecture_plan": empty_architecture_plan(),
            "expanded_files": [],
            "task_breakdown": [],
            "file_contents": {},
            "search_replace_blocks": [],
            "patch_failures": [],
            "file_patches": [],
            "commit_message": "",
            "validation_output": "",
            "validation_passed": False,
            "validation_failures": [],
            "review_history": [],
            "review_approved": False,
            "kb_grounding": "",
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
            "multi-file",
            "kb-grounding",
            "search-replace",
            "patch-engine",
            "error-expansion",
            "log-digest",
            "workspace_setup",
            "requirements_analysis",
            "technical_architecture",
            "error_expansion",
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
        patches = _normalize_patches(final_state.get("file_patches"))

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
        if not patches:
            raise CIFixAgentError("LangGraph agent did not produce any file_patches")

        return FixProposal(
            root_cause=str(final_state.get("root_cause") or "AI-generated fix proposal."),
            commit_message=str(
                final_state.get("commit_message") or "fix: apply AI-generated patch"
            ),
            file_patches=[
                FixFilePatch(file_path=p["file_path"], updated_content=p["updated_content"])
                for p in patches
            ],
            validation_passed=validation_passed if self.validate_enabled else None,
            validation_output=validation_output if self.validate_enabled else None,
            validation_attempts=attempts if self.validate_enabled else None,
            architecture_plan=_plan_as_dict(final_state.get("architecture_plan")),
            kb_grounding=str(final_state.get("kb_grounding") or "") or None,
        )
