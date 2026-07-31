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
from agents.context_pack import (
    assign_roles,
    emit_style_hints_for_pack,
    refine_render_modes,
    render_pack,
)
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
from agents.repo_map import (
    build_repo_map,
    extract_idents_from_text,
    high_confidence_neighbors,
    map_max_files,
)
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
    strategy_type: str = Field(
        description=(
            "One of: deps, import, lint, format, code_patch, config, test. "
            "Choose the category that best matches the diagnosed root cause."
        )
    )
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


class WholeFilePatchModel(BaseModel):
    """Full-file replacement when SEARCH/REPLACE is the wrong tool."""

    file_path: str = Field(description="Relative path of the file to replace entirely")
    updated_content: str = Field(
        description="Complete new file contents — never omit sections with ellipses"
    )


class SearchReplaceProposal(BaseModel):
    root_cause: str = Field(description="Root cause summary")
    blocks: list[SearchReplaceBlockModel] = Field(
        default_factory=list,
        description=(
            "Ordered SEARCH/REPLACE blocks for large/targeted edits; "
            "multiple blocks per file allowed"
        ),
    )
    whole_files: list[WholeFilePatchModel] = Field(
        default_factory=list,
        description=(
            "Full-file replacements ONLY for brand-new files or files where "
            "SEARCH/REPLACE previously failed to apply. Prefer SEARCH/REPLACE "
            "for existing files. When used, copy unchanged lines EXACTLY — "
            "no drive-by cleanup or refactoring."
        ),
    )
    commit_message: str = Field(description="Short conventional commit message")


# Used only as a size gate for post-failure whole-file fallback, not for initial emit.
WHOLE_FILE_FALLBACK_LINE_LIMIT = 120
# Back-compat alias
WHOLE_FILE_LINE_LIMIT = WHOLE_FILE_FALLBACK_LINE_LIMIT


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
Your sole job is to diagnose the root cause of a CI failure from the provided log digest.

Process:
1. Identify the primary exception type or error message (e.g. ModuleNotFoundError,
   TypeError, AssertionError, SyntaxError, YAML parse error, lint violation, etc.).
2. Note the failing file(s) and line number(s) when visible in stack traces.
3. Classify the failure: deps | import | lint | format | config | test | logic | unknown.
4. Do NOT prefer any error family over another — follow the digest.

Hard rules:
- Trust the provided log digest; do not invent failures not present in it.
- If historical KB context is provided, use it to refine the diagnosis only
  when it clearly matches the current failure.
- Be concise. Return only the requested structured fields."""


def _persona_architect() -> str:
    return """You are the Architect Agent for Axolotl CI repair.
Design a minimal, low-blast-radius fix based on the diagnosed root cause.

Process:
1. Choose strategy_type from the evidence in the diagnosis and CI digest:
   deps | import | lint | format | code_patch | config | test
2. List ONLY files that must change to make the failing CI check pass.
   Include same-error siblings when the logs/signature clearly imply them.
3. Do NOT default to requirements.txt unless the diagnosis clearly says
   "missing package" or "ModuleNotFoundError".

Hard rules — CI surgeon, not a refactor bot:
- Propose the smallest change set that clears the failure.
- Do NOT plan refactors, renames, style cleanups, docstring edits, or
  "while we're here" improvements.
- Do NOT add files to affected_files just because they could be improved.

IMPORTANT: CI logs are often fail-fast and may only name ONE broken file. Still
list every file that shares the SAME failing signature. A later error_expansion
stage will search the repo for siblings and enlarge this list when needed.

Return ArchitecturePlan fields only."""


def _persona_tech_lead() -> str:
    return """You are the Tech Lead Agent for Axolotl CI repair.
Turn the ArchitecturePlan into an ordered, dependency-aware checklist (3-6 short steps).
Your checklist should reflect the actual strategy (deps, import, lint, config, test,
code_patch, etc.) — do not assume a specific error family.
If expanded_files lists siblings beyond the seed failure, include a step to fix ALL of them
in the same change set.
Do NOT add refactor, cleanup, or style-improvement tasks.
Do not write code. Return only task_breakdown as a list of strings."""


def _persona_developer() -> str:
    return """You are the Developer Agent for Axolotl CI repair — a precise CI surgeon.
You fix ONLY what is required to make the failing CI check pass.
You are NOT a refactoring assistant and NOT a style linter.

Hard rules — NEVER do drive-by edits:
- Do NOT refactor, rename, reformat, reorder, or "improve" unrelated code.
- Do NOT remove unused imports, dead code, or style issues unless THAT is the
  diagnosed CI failure (e.g. strategy_type is lint/format and those lines failed).
- Do NOT rewrite comments, docstrings, or typing for taste.
- Do NOT touch lines that are not required for the failing check to pass.
- Change only what the failing check requires.
- Trust EVIDENCE over guessed context. Do not invent packages/symbols from
  alias maps, comments, or unloaded AWARENESS paths.
- Only edit files under EDIT TARGETS (unless a HARD RULE explicitly allows otherwise).

Emit style:
- SEARCH/REPLACE (`blocks`) is the DEFAULT for all existing files.
  search_block must be copied CHARACTER-FOR-CHARACTER from the provided file contents.
- Whole-file (`whole_files`) ONLY when:
  (a) the file is NEW (does not exist yet), OR
  (b) a previous SEARCH/REPLACE apply failed for that file.
  When using whole_files, copy every unchanged line EXACTLY from the current
  contents — change only the minimal lines needed for the fix. Never elide with "...".

Strict process rules:
1. Prefer the smallest correct change that resolves the diagnosed root cause.
2. Keep SEARCH/REPLACE blocks minimal — changing lines plus 1-2 anchor lines.
3. Multiple blocks per file are allowed; they apply top to bottom.
4. Empty search_block also creates a new file (legacy); prefer whole_files for new files.
5. Never put line-number prefixes or markdown fences inside blocks or whole_files.
6. If multiple files share the SAME error signature, emit edits for EVERY listed file.
7. A proposal may mix blocks and whole_files across different paths.

Fix guidance (follow the diagnosed root cause — examples, not the only paths):
- Fix the diagnosed root cause in every EDIT TARGET that still has it.
- For missing packages: add ONLY packages named in EVIDENCE / missing-package list
  to the manifest — never packages that merely appear in IMPORT_TO_PACKAGE_MAP.
- For lint/format: patch only the offending lines reported by CI.
- For logic/config/test errors: correct the faulty code, config value, or assertion.

When revising, PRESERVE successful work: emit edits only for what must still change,
guided by validation_failures and review revision_instructions.
If `validation_failures` reports NEW issues introduced by your last patch, fix those.
Do NOT expand blast radius by cleaning unrelated pre-existing lint or style debt."""


def _persona_evaluator() -> str:
    return """You are the Evaluator Agent for Axolotl CI repair.
Your job is to review ONLY the changes the Developer Agent made — NOT pre-existing code quality.

Approval criteria (ALL must be true):
1. The patch correctly addresses the diagnosed root cause.
2. The patch matches the architecture plan's strategy and affected files.
3. The patch does not introduce NEW bugs, syntax errors, or regressions.
4. The patch is STRICTLY minimal — it changes only what is necessary to fix the CI failure.

You MUST REJECT (satisfactory=false) when the DIFF includes drive-by work such as:
- Refactors, renames, reformatting, or reordering unrelated to the root cause
- Removing unused imports / dead code that were NOT the CI failure
- Comment/docstring/typing polish not required by the failing check
- Any change that is not needed for the failing CI check to pass

You MUST IGNORE (do not reject for these alone):
- Pre-existing unused imports, PEP8 issues, or style problems that remain
  unchanged in the ORIGINAL and were NOT introduced or "cleaned" by the patch
- Functions, classes, or logic that the developer did NOT touch
- Any issue visible in ORIGINAL context that the DIFF did not modify

A DIFF section is provided showing exactly what lines were added/removed.
Only evaluate those changes. Approve ONLY if the diff fixes the root cause,
introduces no new bugs, AND contains no unnecessary improvements.

If rejecting: issues MUST cite file paths and line numbers of unnecessary or
newly introduced problems, and revision_instructions must tell the developer
to revert drive-by edits and keep only the minimal CI fix.
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
        workflow.add_node("repo_map", self._repo_map)
        workflow.add_node("task_breakdown", self._task_breakdown)
        workflow.add_node("code_implementation", self._code_implementation)
        workflow.add_node("testing_validation", self._testing_validation)
        workflow.add_node("code_review", self._code_review)

        workflow.add_edge(START, "workspace_setup")
        workflow.add_edge("workspace_setup", "requirements_analysis")
        workflow.add_edge("requirements_analysis", "technical_architecture")
        workflow.add_edge("technical_architecture", "error_expansion")
        workflow.add_edge("error_expansion", "repo_map")
        workflow.add_edge("repo_map", "task_breakdown")
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

        # Slim diagnosis-only prompt — no legacy PromptBuilder (file_path / updated_content).
        # Analyst only needs: project context, log digest, KB grounding, and a root_cause ask.
        human = (
            f"Project: {state['project_id']}\n"
            f"Pipeline: {state['pipeline_id']}\n"
            f"Branch: {state['branch']}\n\n"
            f"CI failure log digest:\n{digest}\n\n"
            + (f"{kb_grounding}\n\n" if kb_grounding else "")
            + 'Diagnose the root cause. Respond with JSON: {"root_cause": "..."}'
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

    @staticmethod
    def _soft_error_hint(signature: dict) -> str:
        """Build an optional soft hint from the error signature.

        This is injected into Architect / Developer prompts so they get
        error-class-specific guidance *only when the digest supports it*.
        Hard rules live in the persona; this is advisory.
        """
        error_class = str(signature.get("error_class") or "unknown")
        if error_class == "unknown":
            return ""
        parts = [f"Error signature hint (optional): class={error_class}"]
        patterns = list(signature.get("patterns") or [])
        if patterns:
            parts.append(f"patterns={json.dumps(patterns[:6])}")
        module = str(signature.get("module_name") or "")
        if module:
            parts.append(f"module={module}")
        lint_codes = list(signature.get("lint_codes") or [])
        if lint_codes:
            parts.append(f"lint_codes={lint_codes[:5]}")
        notes = str(signature.get("notes") or "")
        if notes:
            parts.append(f"notes={notes[:200]}")
        parts.append(
            "Use this hint only if it matches the digest; otherwise follow the digest."
        )
        return "\n".join(parts)

    async def _technical_architecture(self, state: CIFixState) -> dict[str, Any]:
        await self._emit(
            "technical_architecture",
            "Architect (Pro): designing multi-file plan...",
            {"model": self.pro_model},
        )
        # Inject soft error hint when available (from earlier error_signature extraction
        # that runs *after* this stage — on first pass we may not have it yet, but on
        # re-invocations the state carries it forward).  Pre-architecture we derive a
        # lightweight hint from the raw logs so the Architect is not flying blind.
        pre_sig = extract_error_signature(
            state.get("logs") or "",
            root_cause=str(state.get("root_cause") or ""),
            line_hints=dict(state.get("line_hints") or {}),
        )
        soft_hint = self._soft_error_hint(dict(pre_sig))
        human = (
            f"Root cause: {state.get('root_cause')}\n"
            f"KB grounding:\n{state.get('kb_grounding') or '(none)'}\n"
            f"Relevant CI errors (digest):\n{logs_for_llm(state)}\n"
            + (f"\n{soft_hint}\n" if soft_hint else "")
            + "\nProduce ArchitecturePlan JSON. List every affected file."
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

    async def _repo_map(self, state: CIFixState) -> dict[str, Any]:
        """Build a seeded symbol map from MCP-fetched file contents."""
        expanded = [
            normalize_patch_path(p)
            for p in (state.get("expanded_files") or [])
            if p
        ]
        plan = _plan_as_dict(state.get("architecture_plan"))
        seed = list(
            dict.fromkeys(
                expanded
                + [
                    normalize_patch_path(p)
                    for p in (plan.get("affected_files") or [])
                    if p
                ]
                + [
                    normalize_patch_path(p)
                    for p in (state.get("line_hints") or {})
                    if p
                ]
            )
        )
        idents = extract_idents_from_text(
            str(state.get("root_cause") or ""),
            logs_for_llm(state),
            " ".join(str(p) for p in ((state.get("error_signature") or {}).get("patterns") or [])),
        )
        await self._emit(
            "repo_map",
            f"Building seeded symbol map from {len(seed)} seed file(s)...",
            {"seed_files": seed[:12], "idents": sorted(idents)[:20]},
        )

        baseline: dict[str, str] = {
            normalize_patch_path(k): v
            for k, v in dict(state.get("file_contents") or {}).items()
            if v is not None
        }
        for path in seed:
            if path not in baseline:
                fetched = await self._fetch_original(path)
                if fetched is not None:
                    baseline[path] = fetched

        # First pass ranks among known contents; then fetch top unknown neighbors
        # discovered via search_code when the searcher can resolve symbol names.
        _, ranked = build_repo_map(
            seed_files=seed,
            file_contents=baseline,
            mentioned_idents=idents,
            max_files=map_max_files(),
        )

        # Ask the repo searcher for files mentioning high-value idents so the
        # map can pull definition/call-site neighbors not already in expanded.
        neighbor_candidates: list[str] = []
        search_idents = sorted(
            (i for i in idents if len(i) >= 4 and ("_" in i or i[:1].islower())),
            key=len,
            reverse=True,
        )[:5]
        if search_idents:
            neighbor_candidates = await self._search_siblings(search_idents)

        for path in list(dict.fromkeys(ranked + neighbor_candidates)):
            if len(baseline) >= map_max_files() + len(seed):
                break
            if path in baseline:
                continue
            fetched = await self._fetch_original(path)
            if fetched is not None:
                baseline[path] = fetched

        map_text, map_files = build_repo_map(
            seed_files=seed,
            file_contents=baseline,
            mentioned_idents=idents,
            max_files=map_max_files(),
        )
        merge_paths = high_confidence_neighbors(
            ranked_files=map_files,
            seed_files=seed,
            file_contents=baseline,
            mentioned_idents=idents,
        )
        new_expanded = merge_affected_files(
            expanded,
            merge_paths,
            error_class=str((state.get("error_signature") or {}).get("error_class") or "unknown"),
            max_files=max(self.expansion_max_files, map_max_files()),
        )
        plan = {
            **plan,
            "affected_files": new_expanded,
        }

        await self._emit(
            "repo_map",
            (
                f"Repo map ready ({len(map_files)} file(s)"
                + (f", +{len(merge_paths)} symbol neighbor(s)" if merge_paths else "")
                + ")"
            ),
            {
                "map_files": map_files[:20],
                "merged_neighbors": merge_paths[:12],
                "map_chars": len(map_text),
            },
        )
        return {
            "current_stage": "repo_map",
            "repo_map": map_text,
            "map_files": map_files,
            "expanded_files": new_expanded,
            "architecture_plan": plan,
            "file_contents": baseline,
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
            f"Error signature: {json.dumps(state.get('error_signature') or {})}\n"
            f"Repo map:\n{state.get('repo_map') or '(none)'}\n\n"
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
            return (
                f"### {path} (NEW FILE — does not exist yet; "
                "use whole_files with the complete contents, or an empty search_block)"
            )
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
                "Developer (Pro): targeted hybrid revision..."
                if is_revision
                else "Developer (Pro): generating hybrid SEARCH/REPLACE + whole-file proposal..."
            ),
            {
                "model": self.pro_model,
                "attempt": int(state.get("attempts") or 0) + 1,
                "revision": is_revision,
                "affected_files": plan.get("affected_files"),
            },
        )

        expanded = [
            normalize_patch_path(p)
            for p in (state.get("expanded_files") or plan.get("affected_files") or [])
            if p
        ]

        validation_files: list[str] = []
        if is_revision:
            for failure_text in failures:
                for match in re.finditer(
                    r"\b([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]{2,4})\b", failure_text
                ):
                    path_name = normalize_patch_path(match.group(1))
                    if path_name not in validation_files:
                        validation_files.append(path_name)

        existing_paths = [
            normalize_patch_path(p["file_path"]) for p in existing if p.get("file_path")
        ]
        signature = dict(state.get("error_signature") or {})
        missing_pkgs = list(signature.get("missing_packages") or [])
        if not missing_pkgs and signature.get("module_name"):
            missing_pkgs = [str(signature["module_name"]).split(".", 1)[0]]
        pack = assign_roles(
            strategy_type=str(plan.get("strategy_type") or ""),
            error_class=str(signature.get("error_class") or ""),
            seed_files=list(signature.get("seed_files") or []),
            expanded_files=expanded,
            plan_files=[normalize_patch_path(f) for f in (plan.get("affected_files") or [])],
            map_files=[normalize_patch_path(p) for p in (state.get("map_files") or [])],
            validation_files=validation_files,
            existing_patch_files=existing_paths,
            line_hints=hints,
            missing_packages=missing_pkgs,
        )

        # Fetch bodies only for paths we will render (edit + evidence slices).
        for file_path in pack.body_paths:
            if file_path not in baseline:
                baseline[file_path] = await self._fetch_original(file_path)

        refine_render_modes(pack, baseline)

        patched_now = {
            normalize_patch_path(p["file_path"]): p["updated_content"] for p in existing
        }
        working: dict[str, str] = {}
        for file_path in pack.edit_paths:
            if is_revision and file_path in patched_now:
                working[file_path] = patched_now[file_path]
            else:
                working[file_path] = baseline.get(file_path) or ""

        # Contents shown in the prompt: revision shows patched text for edits.
        shown: dict[str, Optional[str]] = {}
        for file_path in pack.body_paths:
            if is_revision and file_path in patched_now and file_path in pack.edit_paths:
                shown[file_path] = patched_now[file_path]
            else:
                shown[file_path] = baseline.get(file_path)

        emit_hints = emit_style_hints_for_pack(
            pack,
            working,
            list(state.get("patch_failures") or []),
            self._prefer_whole_file,
        )
        context_block = render_pack(
            pack,
            shown,
            repo_map=str(state.get("repo_map") or ""),
            digest=logs_for_llm(state) if not is_revision else "",
        )

        await self._emit(
            "code_implementation",
            (
                f"Context pack [{pack.strategy}]: "
                f"{len(pack.edit_paths)} edit / "
                f"{len(pack.awareness_paths)} awareness / "
                f"{len(pack.reference_paths)} reference"
            ),
            {
                "strategy": pack.strategy,
                "edit_paths": pack.edit_paths[:20],
                "awareness_paths": pack.awareness_paths[:20],
                "reference_paths": pack.reference_paths[:10],
                "missing_packages": pack.missing_packages[:20],
            },
        )

        tasks = state.get("task_breakdown") or []
        if is_revision:
            last_critique = history[-1] if history else None
            human = (
                "TARGETED REVISION — emit hybrid edits ONLY for what must still change.\n"
                "Change only what the failing CI check requires. No drive-by refactors, "
                "renames, style cleanup, or unused-import removal unless that IS the failure.\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Expanded files: {json.dumps(expanded)}\n"
                f"Error signature: {json.dumps(signature)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"Emit style hints: {json.dumps(emit_hints)}\n"
                f"validation_failures: {json.dumps(failures[-3:])}\n"
                f"patch apply failures: {json.dumps(list(state.get('patch_failures') or [])[-3:])}\n"
                f"latest critique: {json.dumps(last_critique)}\n\n"
                f"{context_block}\n\n"
                "Return SearchReplaceProposal JSON: blocks and/or whole_files + commit_message. "
                "Prefer SEARCH/REPLACE. Cover every EDIT TARGET that still has the error."
            )
        else:
            soft_hint = self._soft_error_hint(signature)
            human = (
                f"Project: {state['project_id']}\n"
                f"Pipeline: {state['pipeline_id']}\n"
                f"Branch: {state['branch']}\n"
                f"Root cause: {state.get('root_cause')}\n"
                f"KB grounding:\n{state.get('kb_grounding') or '(none)'}\n"
                f"ArchitecturePlan: {json.dumps(plan)}\n"
                f"Expanded files (worklist): {json.dumps(expanded)}\n"
                f"Tasks: {json.dumps(tasks)}\n"
                f"Emit style hints: {json.dumps(emit_hints)}\n"
                f"Failure line hints: {json.dumps(hints) or '(none)'}\n"
                + (f"\n{soft_hint}\n" if soft_hint else "")
                + f"\n{context_block}\n\n"
                "Change only what the failing CI check requires. No drive-by refactors, "
                "renames, style cleanup, or unused-import removal unless that IS the failure.\n"
                "Return SearchReplaceProposal JSON: blocks and/or whole_files + commit_message. "
                "Prefer SEARCH/REPLACE for existing EDIT TARGETS."
            )

        proposal = await self._invoke_search_replace(state, human)
        blocks = list(proposal["blocks"])
        whole_files = list(proposal.get("whole_files") or [])

        for item in whole_files:
            file_path = normalize_patch_path(str(item.get("file_path") or ""))
            if not file_path:
                continue
            if file_path not in working:
                # Opportunistic: allow edits only if we can load the baseline
                if file_path not in baseline:
                    baseline[file_path] = await self._fetch_original(file_path)
                working[file_path] = baseline.get(file_path) or ""
            working[file_path] = str(item.get("updated_content") or "")
            blocks = [
                b
                for b in blocks
                if normalize_patch_path(str(b.get("file_path") or "")) != file_path
            ]

        # Ensure working has baselines for any S/R paths not preloaded as edits
        for block in blocks:
            file_path = normalize_patch_path(str(block.get("file_path") or ""))
            if not file_path or file_path in working:
                continue
            if file_path not in baseline:
                baseline[file_path] = await self._fetch_original(file_path)
            working[file_path] = baseline.get(file_path) or ""

        outcome = apply_blocks(blocks, working, hints, self.fuzzy_threshold)

        patch_failures: list[str] = []
        for failed_block, diagnostics in outcome.failed:
            file_path = normalize_patch_path(str(failed_block.get("file_path") or ""))
            fixed = False
            current = outcome.contents.get(file_path, working.get(file_path, ""))
            if self._allow_whole_file_fallback(
                current, file_path, list(state.get("patch_failures") or [])
            ):
                whole = await self._invoke_whole_file_fix(
                    file_path, current, diagnostics.error, state
                )
                if whole is not None:
                    outcome.contents[file_path] = whole
                    fixed = True
                    await self._emit(
                        "code_implementation",
                        f"Fell back to whole-file rewrite for small/failed path {file_path}",
                        {"file": file_path, "strategy": "whole_file_fallback"},
                    )
            for _ in range(0 if fixed else self.block_retries):
                current = outcome.contents.get(file_path, "")
                nearest = find_nearest_match(
                    current, str(failed_block.get("search_block") or ""), context=12
                )
                feedback = build_block_failure_feedback(
                    file_path=file_path,
                    error=diagnostics.error,
                    nearest_match=nearest,
                    applied_count=len(outcome.applied),
                    total_count=len(blocks),
                )
                await self._emit(
                    "code_implementation",
                    f"Block failed in {file_path}; requesting targeted fix (cached "
                    f"{len(outcome.applied)}/{len(blocks)} applied blocks)...",
                    {"file": file_path, "error": diagnostics.error[:300]},
                )
                candidate = await self._invoke_block_fix(failed_block, feedback)
                if candidate is None:
                    continue
                retry = apply_fuzzy_patch(
                    current,
                    candidate.get("search_block") or "",
                    candidate.get("replace_block") or "",
                    line_hint=line_hint_for(hints, file_path),
                    threshold=self.fuzzy_threshold,
                )
                if retry.success:
                    outcome.contents[file_path] = retry.content
                    outcome.applied.append(candidate)
                    fixed = True
                    break
                diagnostics = retry
                failed_block = candidate
            if not fixed:
                patch_failures.append(f"{file_path}: {diagnostics.error}")

        for file_path, content in working.items():
            if file_path not in outcome.contents:
                outcome.contents[file_path] = content

        patches: list[FilePatch] = [
            {"file_path": file_path, "updated_content": content}
            for file_path, content in outcome.contents.items()
            if content != (baseline.get(file_path) or "")
        ]

        paths = [p["file_path"] for p in patches]
        await self._emit(
            "code_implementation",
            (
                f"Applied {len(outcome.applied)} S/R block(s) + {len(whole_files)} whole-file(s) "
                f"across {len(paths)} file(s): {', '.join(paths[:5])} — {proposal['commit_message']}"
                + (f" | {len(patch_failures)} block(s) unresolved" if patch_failures else "")
            ),
            {
                "files": paths,
                "applied_blocks": len(outcome.applied),
                "whole_files": len(whole_files),
                "failed_blocks": len(patch_failures),
                "commit_message": proposal["commit_message"],
            },
        )
        return {
            "current_stage": "code_implementation",
            "root_cause": proposal["root_cause"] or state.get("root_cause") or "",
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

    @staticmethod
    def _prefer_whole_file(
        content: str, file_path: str, prior_failures: list[str]
    ) -> bool:
        """Initial emit preference: whole-file only for new files or prior S/R failures."""
        if not content.strip():
            return True
        if any(file_path in failure for failure in prior_failures):
            return True
        return False

    @staticmethod
    def _allow_whole_file_fallback(
        content: str, file_path: str, prior_failures: list[str]
    ) -> bool:
        """
        After a SEARCH/REPLACE apply failure, allow one whole-file retry for
        new/prior-failed paths or reasonably small files (fallback size gate only).
        """
        if LangGraphCIFixAgent._prefer_whole_file(content, file_path, prior_failures):
            return True
        return content.count("\n") + 1 <= WHOLE_FILE_FALLBACK_LINE_LIMIT

    def _emit_style_hints(
        self, working: dict[str, str], prior_failures: list[str]
    ) -> dict[str, str]:
        hints: dict[str, str] = {}
        for file_path, content in working.items():
            if self._prefer_whole_file(content, file_path, prior_failures):
                hints[file_path] = "prefer_whole_file"
            else:
                hints[file_path] = "prefer_search_replace"
        return hints

    async def _invoke_whole_file_fix(
        self,
        file_path: str,
        current: str,
        error: str,
        state: CIFixState,
    ) -> Optional[str]:
        """One-shot whole-file rewrite for new/failed SEARCH/REPLACE paths."""
        human = (
            f"SEARCH/REPLACE failed for `{file_path}`: {error}\n"
            "Return ONLY a WholeFilePatch JSON object with the COMPLETE updated file:\n"
            '{"file_path": "...", "updated_content": "..."}\n\n'
            "CRITICAL: Copy every unchanged line EXACTLY from the current contents. "
            "Change only the minimal lines needed for the CI fix. "
            "Do NOT refactor, reformat, rename, or remove unused imports unless "
            "that is the diagnosed root cause.\n"
            f"Root cause: {state.get('root_cause')}\n"
            f"Current file contents:\n{current}\n"
        )
        structured = self.llm_pro.with_structured_output(WholeFilePatchModel)
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
            )
            patch = (
                result
                if isinstance(result, WholeFilePatchModel)
                else WholeFilePatchModel.model_validate(result)
            )
            return str(patch.updated_content)
        except Exception:
            try:
                response = await self.llm_pro.ainvoke(
                    [SystemMessage(content=_persona_developer()), HumanMessage(content=human)]
                )
                payload = _extract_json_object(getattr(response, "content", "") or "")
                if payload.get("updated_content") is not None:
                    return str(payload.get("updated_content"))
            except Exception as exc:
                print(f"[PatchEngine] Whole-file fallback failed: {exc}")
        return None

    async def _invoke_search_replace(self, state: CIFixState, human: str) -> dict[str, Any]:
        """Single-pass generation of hybrid SEARCH/REPLACE + whole-file edits."""
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
            whole_files = [w.model_dump() for w in proposal.whole_files]
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
            raw_whole = payload.get("whole_files") or []
            whole_files = [
                {
                    "file_path": str(w.get("file_path", "")),
                    "updated_content": str(w.get("updated_content", "")),
                }
                for w in raw_whole
                if isinstance(w, dict)
            ]
            root_cause = str(payload.get("root_cause", state.get("root_cause") or "AI fix"))
            commit_message = str(
                payload.get("commit_message", "fix: apply AI-generated patch")
            )

        return {
            "blocks": [b for b in blocks if str(b.get("file_path") or "").strip()],
            "whole_files": [
                w for w in whole_files if str(w.get("file_path") or "").strip()
            ],
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
            original_contents=baseline,
            strategy_type=str(
                (state.get("architecture_plan") or {}).get("strategy_type") or ""
            ),
            error_signature=signature,
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
            "Approve ONLY if the diff fixes the root cause, introduces no new bugs, "
            "AND is strictly minimal.\n"
            "REJECT drive-by edits: refactors, renames, reformatting, unused-import "
            "cleanup, comment/docstring polish, or any change not required for the "
            "failing CI check.\n"
            "Do NOT reject for pre-existing issues that remain unchanged in ORIGINAL "
            "and were not introduced by the DIFF.\n"
            "Return CritiqueResult."
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
            "repo_map": "",
            "map_files": [],
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
            "repo-map",
            "hybrid-emit",
            "log-digest",
            "workspace_setup",
            "requirements_analysis",
            "technical_architecture",
            "error_expansion",
            "repo_map",
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
