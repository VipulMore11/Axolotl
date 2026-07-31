"""
Context Pack — tiered, strategy-aware prompt assembly for CI repair.

Replaces "dump every fetched file into the Developer prompt" with three tiers:

  A. Evidence   — digest findings, structured missing packages, lint codes
  B. Edit       — files expected to be patched (full or windowed bodies)
  C. Awareness  — paths / repo-map outlines only (never full bodies by default)

Roles are assigned by strategy profile; map neighbors are awareness unless also
an edit candidate. Callers may promote awareness → edit via retrieve_more.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FileRole(str, Enum):
    EDIT = "edit"
    EVIDENCE = "evidence"
    AWARENESS = "awareness"
    REFERENCE = "reference"  # diagnostic helpers — do not edit; slice or omit


class RenderMode(str, Enum):
    FULL = "full"
    WINDOW = "window"
    IMPORTS = "imports"
    PATH_ONLY = "path_only"


# Manifests / lockfiles that are safe to send whole for deps fixes.
_MANIFEST_BASENAMES = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "environment.yml",
        "conda.yaml",
    }
)

_CHECKER_BASENAME_RE = re.compile(
    r"(?i)^(check_?(requirements|deps|dependencies)|verify_?(requirements|deps))\.py$"
)
_CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".cfg", ".ini", ".json")
_CI_BASENAMES = frozenset(
    {".gitlab-ci.yml", ".github/workflows", "Jenkinsfile", "azure-pipelines.yml"}
)

_IMPORT_LINE_RE = re.compile(r"^\s*(?:import\s+\S+|from\s+\S+\s+import\b)")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def full_file_char_cap() -> int:
    return _env_int("CI_FIX_CONTEXT_FULL_CHAR_CAP", 12000)


def window_radius_lines() -> int:
    return _env_int("CI_FIX_CONTEXT_WINDOW_LINES", 80)


def import_head_max_lines() -> int:
    return _env_int("CI_FIX_CONTEXT_IMPORT_LINES", 50)


def normalize_strategy(
    strategy_type: str = "",
    error_class: str = "",
) -> str:
    """Collapse plan strategy + signature class into one policy key."""
    for raw in (strategy_type, error_class):
        key = (raw or "").strip().lower()
        if key in {"deps", "import", "lint", "format", "name", "config", "test", "code_patch"}:
            return key
    return "code_patch"


def is_manifest(path: str) -> bool:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    return base in _MANIFEST_BASENAMES


def is_checker_script(path: str) -> bool:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(_CHECKER_BASENAME_RE.match(base))


def is_config_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    base = norm.rsplit("/", 1)[-1]
    if base in _CI_BASENAMES or any(norm.endswith(s) for s in _CI_BASENAMES if "/" in s):
        return True
    if "/.github/workflows/" in f"/{norm}":
        return True
    return any(norm.endswith(suf) for suf in _CONFIG_SUFFIXES)


@dataclass
class ContextFile:
    path: str
    role: FileRole
    render_mode: RenderMode
    line_hint: Optional[int] = None
    note: str = ""


@dataclass
class ContextPack:
    strategy: str
    evidence_notes: list[str] = field(default_factory=list)
    files: list[ContextFile] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    missing_packages: list[str] = field(default_factory=list)

    @property
    def edit_paths(self) -> list[str]:
        return [f.path for f in self.files if f.role == FileRole.EDIT]

    @property
    def body_paths(self) -> list[str]:
        """Paths that need content fetched for rendering (not path-only)."""
        return [
            f.path
            for f in self.files
            if f.render_mode != RenderMode.PATH_ONLY
        ]

    @property
    def awareness_paths(self) -> list[str]:
        return [f.path for f in self.files if f.role == FileRole.AWARENESS]

    @property
    def reference_paths(self) -> list[str]:
        return [f.path for f in self.files if f.role == FileRole.REFERENCE]


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        path = (raw or "").replace("\\", "/").strip()
        while path.startswith("./"):
            path = path[2:]
        path = path.lstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _choose_edit_mode(path: str, content: Optional[str], line_hint: Optional[int]) -> RenderMode:
    if content is None or not str(content).strip():
        return RenderMode.FULL  # new / empty — whole_files
    if is_manifest(path):
        return RenderMode.FULL
    if len(content) <= full_file_char_cap():
        # Still window when we have a precise failure line and file is non-trivial
        lines = content.count("\n") + 1
        if line_hint and lines > window_radius_lines() * 2:
            return RenderMode.WINDOW
        return RenderMode.FULL
    return RenderMode.WINDOW


def assign_roles(
    *,
    strategy_type: str = "",
    error_class: str = "",
    seed_files: Optional[list[str]] = None,
    expanded_files: Optional[list[str]] = None,
    plan_files: Optional[list[str]] = None,
    map_files: Optional[list[str]] = None,
    validation_files: Optional[list[str]] = None,
    existing_patch_files: Optional[list[str]] = None,
    line_hints: Optional[dict[str, int]] = None,
    missing_packages: Optional[list[str]] = None,
) -> ContextPack:
    """
    Build a role-tagged pack from graph artifacts.

    map_files are awareness unless they also qualify as edit candidates.
    """
    strategy = normalize_strategy(strategy_type, error_class)
    hints = {k.replace("\\", "/"): int(v) for k, v in (line_hints or {}).items()}
    seeds = _unique_paths(list(seed_files or []) + list(hints.keys()))
    expanded = _unique_paths(list(expanded_files or []))
    planned = _unique_paths(list(plan_files or []))
    mapped = _unique_paths(list(map_files or []))
    validation = _unique_paths(list(validation_files or []))
    existing = _unique_paths(list(existing_patch_files or []))
    pkgs = _unique_paths([p.lower() for p in (missing_packages or [])])

    edit: list[str] = []
    evidence: list[str] = []
    reference: list[str] = []
    awareness: list[str] = []

    def _add(bucket: list[str], path: str) -> None:
        if path and path not in bucket:
            bucket.append(path)

    if strategy == "deps":
        # Edit manifests only; checkers are reference; everything else awareness.
        for path in planned + expanded + seeds + existing + validation:
            if is_manifest(path):
                _add(edit, path)
            elif is_checker_script(path):
                _add(reference, path)
            elif is_config_path(path):
                _add(awareness, path)
            else:
                # Importers cited by CI may be evidence (import heads), not edits.
                _add(evidence, path)
        for path in mapped:
            if path not in edit and path not in reference and path not in evidence:
                _add(awareness, path)
        if not edit:
            _add(edit, "requirements.txt")

    elif strategy in {"lint", "format"}:
        for path in seeds + validation + existing + expanded:
            if is_checker_script(path):
                _add(reference, path)
            else:
                _add(edit, path)
        for path in planned:
            if path not in edit:
                _add(edit, path)
        for path in mapped:
            if path not in edit:
                _add(awareness, path)

    elif strategy == "config":
        for path in planned + seeds + expanded + existing + validation:
            if is_config_path(path) or is_manifest(path):
                _add(edit, path)
            else:
                _add(awareness, path)
        for path in mapped:
            if path not in edit:
                _add(awareness, path)

    elif strategy in {"import", "name", "test", "code_patch"}:
        for path in seeds + existing + validation:
            _add(edit, path)
        for path in expanded + planned:
            if is_manifest(path) and strategy in {"import", "code_patch"}:
                # Optional dep pin alongside import fix — keep as edit if planned
                _add(edit, path)
            elif is_checker_script(path):
                _add(reference, path)
            elif path in seeds or path in existing or path in validation:
                continue
            else:
                # Same-error siblings: edit; pure map neighbors handled below
                if path in expanded or path in planned:
                    _add(edit, path)
        for path in mapped:
            if path not in edit and path not in reference:
                _add(awareness, path)

    else:
        for path in seeds + existing + validation + expanded + planned:
            _add(edit, path)
        for path in mapped:
            if path not in edit:
                _add(awareness, path)

    # Drop overlaps: edit wins over evidence/awareness/reference
    edit_set = set(edit)
    evidence = [p for p in evidence if p not in edit_set]
    reference = [p for p in reference if p not in edit_set and p not in evidence]
    awareness = [
        p
        for p in awareness
        if p not in edit_set and p not in evidence and p not in reference
    ]

    files: list[ContextFile] = []
    for path in edit:
        hint = hints.get(path)
        # Mode refined later when content is known; provisional FULL/WINDOW
        mode = RenderMode.WINDOW if hint else RenderMode.FULL
        if is_manifest(path):
            mode = RenderMode.FULL
        files.append(
            ContextFile(
                path=path,
                role=FileRole.EDIT,
                render_mode=mode,
                line_hint=hint,
                note="edit target",
            )
        )
    for path in evidence:
        files.append(
            ContextFile(
                path=path,
                role=FileRole.EVIDENCE,
                render_mode=RenderMode.IMPORTS,
                line_hint=hints.get(path),
                note="import heads only — not an edit target",
            )
        )
    for path in reference:
        files.append(
            ContextFile(
                path=path,
                role=FileRole.REFERENCE,
                render_mode=RenderMode.PATH_ONLY,
                note="diagnostic script — do not edit; do not treat alias maps as install lists",
            )
        )
    for path in awareness:
        files.append(
            ContextFile(
                path=path,
                role=FileRole.AWARENESS,
                render_mode=RenderMode.PATH_ONLY,
                note="available path — not loaded; do not invent edits here",
            )
        )

    rules = _rules_for_strategy(strategy, pkgs)
    notes: list[str] = []
    if pkgs:
        notes.append("Missing packages from CI evidence: " + ", ".join(pkgs))
    notes.append(
        f"Context policy [{strategy}]: "
        f"{len(edit)} edit, {len(evidence)} evidence, "
        f"{len(reference)} reference, {len(awareness)} awareness"
    )

    return ContextPack(
        strategy=strategy,
        evidence_notes=notes,
        files=files,
        rules=rules,
        missing_packages=pkgs,
    )


def refine_render_modes(
    pack: ContextPack,
    contents: dict[str, Optional[str]],
) -> ContextPack:
    """Upgrade provisional edit modes using actual file sizes / hints."""
    for item in pack.files:
        if item.role != FileRole.EDIT:
            continue
        content = contents.get(item.path)
        item.render_mode = _choose_edit_mode(item.path, content, item.line_hint)
    return pack


def _rules_for_strategy(strategy: str, missing_packages: list[str]) -> list[str]:
    rules = [
        "Change only what the failing CI check requires. No drive-by refactors.",
        "Do not invent symbols, packages, or APIs that are not in EVIDENCE or EDIT TARGETS.",
        "Files listed under AWARENESS / REFERENCE are not loaded — do not edit them unless promoted.",
        "Prefer SEARCH/REPLACE for existing edit targets; whole_files only for new/empty or prior S/R failures.",
    ]
    if strategy == "deps":
        rules.extend(
            [
                "Edit dependency manifests only (requirements.txt / pyproject.toml / lockfiles).",
                "IMPORT_TO_PACKAGE_MAP (and similar alias tables) are name translations — "
                "NEVER add a package only because it appears in such a map.",
            ]
        )
        if missing_packages:
            rules.append(
                "Only add packages named in the CI missing-deps evidence: "
                + ", ".join(missing_packages)
                + ". If the list is empty, do not guess from checker source."
            )
        else:
            rules.append(
                "If CI did not name missing packages, do not invent a shopping list — "
                "ask for evidence or leave manifests unchanged except clear ModuleNotFound names."
            )
    elif strategy in {"lint", "format"}:
        rules.append("Only touch lines/files cited by lint/format findings.")
    elif strategy == "config":
        rules.append("Only edit CI/config files required to fix the failure.")
    return rules


def extract_import_head(content: str, max_lines: int | None = None) -> str:
    """Keep import/from lines (and light module docstring) from the file head."""
    max_lines = max_lines or import_head_max_lines()
    if not content:
        return ""
    lines = content.splitlines()
    kept: list[str] = []
    past_header = False
    for i, line in enumerate(lines):
        if i >= max_lines * 3:
            break
        stripped = line.strip()
        if not stripped:
            if kept and past_header:
                break
            kept.append(line)
            continue
        if stripped.startswith("#") or stripped.startswith(('"""', "'''")):
            kept.append(line)
            continue
        if _IMPORT_LINE_RE.match(line):
            kept.append(line)
            past_header = True
            if len([ln for ln in kept if _IMPORT_LINE_RE.match(ln)]) >= max_lines:
                break
            continue
        if past_header:
            break
        # Non-import before any import — skip body noise
        if i > 15:
            break
    text = "\n".join(kept).strip()
    return text or "\n".join(lines[: min(20, len(lines))])


def render_file_section(
    item: ContextFile,
    content: Optional[str],
    *,
    window_lines: int | None = None,
) -> str:
    """Render one file according to its role/mode."""
    path = item.path
    role = item.role.value
    note = f" — {item.note}" if item.note else ""

    if item.render_mode == RenderMode.PATH_ONLY or content is None and item.role != FileRole.EDIT:
        return f"### {path} [{role}]{note}\n(path only — content not loaded)"

    if content is None:
        return (
            f"### {path} [{role}]{note}\n"
            "(NEW FILE — does not exist yet; use whole_files with complete contents, "
            "or an empty search_block)"
        )

    if item.render_mode == RenderMode.IMPORTS:
        head = extract_import_head(content)
        return f"### {path} [{role}/imports]{note}\n{head}"

    if item.render_mode == RenderMode.WINDOW:
        radius = window_lines or window_radius_lines()
        lines = content.splitlines()
        center = (item.line_hint - 1) if item.line_hint else len(lines) // 2
        lo = max(0, center - radius)
        hi = min(len(lines), center + radius)
        head = "\n".join(lines[: min(30, lo)])
        window = "\n".join(lines[lo:hi])
        parts = [
            f"### {path} [{role}/window]{note} "
            f"(file has {len(lines)} lines; showing head + lines {lo + 1}-{hi})"
        ]
        if head.strip() and lo > 0:
            parts.append(head)
            parts.append("... (lines omitted) ...")
        parts.append(window)
        if hi < len(lines):
            parts.append("... (lines omitted) ...")
        return "\n".join(parts)

    # FULL
    return f"### {path} [{role}]{note}\n{content}"


def render_pack(
    pack: ContextPack,
    contents: dict[str, Optional[str]],
    *,
    repo_map: str = "",
    digest: str = "",
) -> str:
    """
    Assemble the FILE / EVIDENCE sections for a Developer (or similar) prompt.
    """
    sections: list[str] = []

    sections.append("═══ EVIDENCE (must drive the fix) ═══")
    if digest.strip():
        sections.append(digest.strip())
    for note in pack.evidence_notes:
        sections.append(f"- {note}")
    if pack.missing_packages:
        sections.append(
            "Missing packages (authoritative): " + ", ".join(pack.missing_packages)
        )
    if not digest.strip() and not pack.evidence_notes and not pack.missing_packages:
        sections.append("(no extra structured evidence)")

    sections.append("\n═══ EDIT TARGETS (search blocks must match this text) ═══")
    edit_items = [f for f in pack.files if f.role == FileRole.EDIT]
    if not edit_items:
        sections.append("(no edit targets)")
    for item in edit_items:
        sections.append(render_file_section(item, contents.get(item.path)))

    evidence_items = [f for f in pack.files if f.role == FileRole.EVIDENCE]
    if evidence_items:
        sections.append("\n═══ EVIDENCE SLICES (context only — do not edit unless required) ═══")
        for item in evidence_items:
            sections.append(render_file_section(item, contents.get(item.path)))

    ref_items = [f for f in pack.files if f.role == FileRole.REFERENCE]
    aware_items = [f for f in pack.files if f.role == FileRole.AWARENESS]
    if ref_items or aware_items:
        sections.append("\n═══ AWARENESS / REFERENCE (not loaded — do not invent edits) ═══")
        for item in ref_items + aware_items:
            sections.append(render_file_section(item, None))

    if repo_map.strip() and repo_map.strip() != "(none)":
        sections.append("\n═══ REPO MAP (outline only) ═══")
        sections.append(repo_map.strip())

    sections.append("\n═══ HARD RULES ═══")
    for rule in pack.rules:
        sections.append(f"- {rule}")

    return "\n\n".join(sections)


def emit_style_hints_for_pack(
    pack: ContextPack,
    contents: dict[str, str],
    prior_failures: list[str],
    prefer_whole_file_fn: Any,
) -> dict[str, str]:
    """Emit-style hints only for edit targets (not awareness dumps)."""
    hints: dict[str, str] = {}
    for path in pack.edit_paths:
        content = contents.get(path, "")
        if prefer_whole_file_fn(content, path, prior_failures):
            hints[path] = "prefer_whole_file"
        else:
            hints[path] = "prefer_search_replace"
    return hints


def promote_to_edit(
    pack: ContextPack,
    paths: list[str],
    *,
    line_hints: Optional[dict[str, int]] = None,
) -> ContextPack:
    """Promote awareness/evidence paths to edit (e.g. after retrieve_more)."""
    hints = {k.replace("\\", "/"): int(v) for k, v in (line_hints or {}).items()}
    want = set(_unique_paths(paths))
    if not want:
        return pack
    existing = {f.path: f for f in pack.files}
    for path in want:
        hint = hints.get(path)
        if path in existing:
            item = existing[path]
            item.role = FileRole.EDIT
            item.render_mode = RenderMode.WINDOW if hint else RenderMode.FULL
            item.line_hint = hint or item.line_hint
            item.note = "promoted to edit"
        else:
            pack.files.append(
                ContextFile(
                    path=path,
                    role=FileRole.EDIT,
                    render_mode=RenderMode.WINDOW if hint else RenderMode.FULL,
                    line_hint=hint,
                    note="promoted to edit",
                )
            )
    return pack
