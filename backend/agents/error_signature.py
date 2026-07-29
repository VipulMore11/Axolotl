"""
Error signature extraction and same-error fan-out helpers.

CI logs are treated as a *seed*: one failing file/line is usually enough to
derive a searchable pattern so sibling files with the same bug can be found
even when fail-fast CI never printed them.
"""

from __future__ import annotations

import re
from typing import Any, Optional, TypedDict

from agents.patch_utils import extract_line_hints, normalize_patch_path

# Code-ish paths worth scanning during fan-out (keep cheap / text-only).
_CODE_SUFFIXES = (
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".java",
    ".go",
    ".rb",
    ".rs",
    ".php",
    ".cs",
    ".kt",
    ".swift",
    ".scala",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".yml",
    ".yaml",
    ".json",
)

_SKIP_DIR_PREFIXES = (
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".tox/",
    ".mypy_cache/",
    ".pytest_cache/",
    "vendor/",
)

_MODULE_NOT_FOUND_RE = re.compile(
    r"No module named ['\"]([^'\"]+)['\"]", re.IGNORECASE
)
_IMPORT_ERROR_RE = re.compile(
    r"cannot import name ['\"]([^'\"]+)['\"]", re.IGNORECASE
)
_NAME_ERROR_RE = re.compile(r"NameError:\s*name ['\"](\w+)['\"] is not defined", re.IGNORECASE)
_LINT_CODE_RE = re.compile(r"\b([A-Z]\d{3,4})\b")  # E302, F401, …
_BAD_IMPORT_LINE_RE = re.compile(
    r"^\s*((?:from\s+\S+\s+)?import\s+[^\n#]+)", re.MULTILINE | re.IGNORECASE
)
_STACK_LINE_CONTENT_RE = re.compile(
    r'File "[^"]+", line \d+[^\n]*\n\s*(.+)'
)


class ErrorSignature(TypedDict, total=False):
    error_class: str  # deps | import | lint | format | name | unknown
    module_name: str
    lint_codes: list[str]
    seed_files: list[str]
    seed_lines: dict[str, int]
    patterns: list[str]  # literal / light-regex strings for repo search
    notes: str


def is_searchable_path(path: str) -> bool:
    """Return True when a repo path is worth opening during fan-out."""
    normalized = normalize_patch_path(path)
    lower = normalized.lower()
    if any(lower.startswith(prefix) or f"/{prefix}" in f"/{lower}" for prefix in _SKIP_DIR_PREFIXES):
        return False
    basename = lower.rsplit("/", 1)[-1]
    if basename in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.cfg"}:
        return True
    return any(lower.endswith(suffix) for suffix in _CODE_SUFFIXES)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def extract_error_signature(
    logs: str,
    root_cause: str = "",
    line_hints: Optional[dict[str, int]] = None,
) -> ErrorSignature:
    """
    Derive a searchable error signature from CI logs + diagnosis.

    Patterns are ordered most-specific first so repo search can stop early
    when enough sibling hits are found.
    """
    logs = logs or ""
    root_cause = root_cause or ""
    combined = f"{logs}\n{root_cause}"
    hints = dict(line_hints or extract_line_hints(logs))
    seed_files = [normalize_patch_path(p) for p in hints.keys()]

    patterns: list[str] = []
    lint_codes: list[str] = []
    module_name = ""
    error_class = "unknown"
    notes_parts: list[str] = []

    mod_match = _MODULE_NOT_FOUND_RE.search(combined)
    if mod_match:
        module_name = mod_match.group(1).strip()
        top = module_name.split(".", 1)[0]
        error_class = "deps"
        patterns.extend(
            [
                f"import {top}",
                f"from {top} ",
                f"from {top}.",
                f"import {module_name}",
                f"from {module_name} ",
            ]
        )
        notes_parts.append(f"missing module '{module_name}'")

    import_name = _IMPORT_ERROR_RE.search(combined)
    if import_name:
        error_class = "import" if error_class == "unknown" else error_class
        name = import_name.group(1).strip()
        patterns.append(name)
        notes_parts.append(f"import name '{name}'")

    # Exact failing source line from the traceback (best sibling fan-out signal)
    for match in _STACK_LINE_CONTENT_RE.finditer(logs):
        line = match.group(1).strip()
        if not line or line.startswith(("File ", "Traceback", "During handling")):
            continue
        if len(line) >= 4:
            patterns.insert(0, line)
            # Prefer import-ish failures as code_patch fan-out
            if "import" in line.lower() and error_class in {"unknown", "deps"}:
                error_class = "import"
            notes_parts.append(f"seed line `{line[:80]}`")

    # Bare import lines mentioned anywhere in the log body
    for match in _BAD_IMPORT_LINE_RE.finditer(logs):
        patterns.append(match.group(1).strip())

    name_err = _NAME_ERROR_RE.search(combined)
    if name_err:
        error_class = "name" if error_class == "unknown" else error_class
        patterns.append(name_err.group(1))

    for code in _LINT_CODE_RE.findall(combined):
        if code not in lint_codes:
            lint_codes.append(code)
    if lint_codes and error_class == "unknown":
        error_class = "lint"
        notes_parts.append("lint codes: " + ", ".join(lint_codes[:5]))

    logs_lower = combined.lower()
    if any(token in logs_lower for token in ("black would reformat", "ruff format", "would reformat")):
        error_class = "format"
    elif "modulenotfounderror" in logs_lower and error_class == "unknown":
        error_class = "deps"

    # Root-cause free text: pull short quoted tokens / identifiers as weak patterns
    for quoted in re.findall(r"['\"]([A-Za-z_][\w./-]{2,})['\"]", root_cause):
        if quoted not in patterns and quoted.lower() not in {"true", "false", "none"}:
            patterns.append(quoted)

    patterns = _unique(patterns)

    return ErrorSignature(
        error_class=error_class,
        module_name=module_name,
        lint_codes=lint_codes,
        seed_files=seed_files,
        seed_lines={normalize_patch_path(k): int(v) for k, v in hints.items()},
        patterns=patterns,
        notes="; ".join(_unique(notes_parts)) or "generic CI failure seed",
    )


def content_matches_patterns(content: str, patterns: list[str]) -> list[str]:
    """
    Return which patterns appear in `content`.

    Uses token-boundary matching so `import request` does not hit `import requests`.
    """
    hits: list[str] = []
    if not content or not patterns:
        return hits
    for pattern in patterns:
        if not pattern:
            continue
        # Boundary: not preceded/followed by a word character (identifier-safe).
        regex = re.compile(rf"(?<![\w]){re.escape(pattern)}(?![\w])")
        if regex.search(content):
            hits.append(pattern)
    return hits


def merge_affected_files(
    planned: list[str],
    discovered: list[str],
    *,
    error_class: str = "unknown",
    max_files: int = 25,
) -> list[str]:
    """
    Merge Architect's plan with fan-out discoveries.

    For pure dependency fixes we still keep requirements*.txt first, but also
    retain discovered import sites so broken imports across files get patched.
    """
    merged: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        path = normalize_patch_path(path)
        if not path or path in seen:
            return
        seen.add(path)
        merged.append(path)

    for path in planned or []:
        _add(path)

    # Prefer requirements files early for deps-class failures
    if error_class == "deps":
        for path in discovered or []:
            if path.replace("\\", "/").endswith("requirements.txt") or path.endswith(
                "pyproject.toml"
            ):
                _add(path)

    for path in discovered or []:
        _add(path)
        if len(merged) >= max_files:
            break

    return merged[:max_files]


def actionable_cleanup_patterns(signature: ErrorSignature) -> list[str]:
    """
    Patterns that should disappear from the codebase after a complete fix.

    For missing-module (deps) failures, `import requests` is legitimate usage and
    must NOT force another loop — only the seed failing line / typo patterns count.
    """
    patterns = list(signature.get("patterns") or [])
    error_class = str(signature.get("error_class") or "unknown")
    module_name = str(signature.get("module_name") or "").strip()
    if error_class != "deps" or not module_name:
        return patterns

    top = module_name.split(".", 1)[0]
    legitimate = {
        f"import {top}",
        f"from {top} ",
        f"from {top}.",
        f"import {module_name}",
        f"from {module_name} ",
        module_name,
        top,
    }
    cleaned = [p for p in patterns if p not in legitimate]
    # If everything was filtered, keep only long seed-line style patterns
    if not cleaned:
        cleaned = [p for p in patterns if len(p) >= 12 and "import" in p.lower()]
    return cleaned


def remaining_signature_hits(
    file_contents: dict[str, str],
    patterns: list[str],
    *,
    patched_paths: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """
    After patching, report expanded files that still contain the seed patterns.

    Used by testing_validation to force another Stage 5 loop when siblings were
    discovered but not fully cleaned.
    """
    patched_paths = patched_paths or set()
    leftovers: list[dict[str, Any]] = []
    for path, content in (file_contents or {}).items():
        hits = content_matches_patterns(content or "", patterns)
        if hits:
            leftovers.append(
                {
                    "file_path": normalize_patch_path(path),
                    "patterns": hits,
                    "was_patched": normalize_patch_path(path) in patched_paths,
                }
            )
    return leftovers
