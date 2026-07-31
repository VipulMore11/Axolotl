"""
Deterministic CI log reducer.

Full pipeline traces are kept in state for regex tooling (line hints, error
signatures, fan-out). LLMs only see a compact `logs_digest` built here so they
are not distracted by pip/Docker/passed-test noise.

No LLM calls — pure heuristics, stable and testable.
"""

from __future__ import annotations

import os
import re
from typing import Any, TypedDict

# ── Tunables (overridable via env) ──────────────────────────────────

DEFAULT_MAX_DIGEST_CHARS = 3500
DEFAULT_TAIL_LINES = 120
DEFAULT_MAX_ERROR_BLOCKS = 12


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# ── Noise / signal patterns ─────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\r")

_NOISE_LINE_RE = re.compile(
    r"(?i)^(?:\s*"
    r"(?:Downloading|Downloaded|Download\s|Using cached|Cached|"
    r"Requirement already satisfied|Collecting\s|Installing collected|"
    r"Successfully installed|Looking in indexes|"
    r"Fetching\s|Resolving\s|Cloning\s|Unpacking\s|"
    r"Pulling\s|Already up to date|"
    r"#\d+\s+\d+\.\d+\s+(?:MiB|KiB|GiB)|"  # docker progress-ish
    r"Progress\s*\(|"
    r"httpx\.(?:connect|read|send)|"
    r"DEBUG\s*[:|]|"
    r"\*\*\*+\s*$|"
    r"-{10,}\s*$"
    r").*)"
)

_SECTION_BANNER_RE = re.compile(r"^={5,}.*$|^-{5,}.*$|^\*{5,}.*$")

_TRACEBACK_START_RE = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
_EXCEPTION_LINE_RE = re.compile(
    r"^\s*(?:\w+\.)*?(?:"
    r"Error|Exception|Failure|Fatal|Panic"
    r")\b.*|"
    r"^\s*(?:ModuleNotFoundError|ImportError|SyntaxError|NameError|TypeError|"
    r"AttributeError|ValueError|KeyError|RuntimeError|AssertionError|"
    r"CalledProcessError|IndentationError|TabError)\b.*"
)
_PYTEST_E_RE = re.compile(r"^\s*E\s+.+")
_PYTEST_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+\S+")
_LINT_FINDING_RE = re.compile(
    r"(?<![\w:/])((?:[A-Za-z]:)?[\w.\-]+(?:[/\\][\w.\-]+)*\.[A-Za-z]\w{0,9}):(\d+)(?::\d+)?:\s*([A-Z]\d{3,4}|error|warning)\b.*"
)
_ERROR_KEYWORD_RE = re.compile(
    r"(?i)\b(?:error|failed|failure|fatal|exception|traceback|panic|critical)\b"
)
_WARNING_KEYWORD_RE = re.compile(r"(?i)\b(?:warning|warn)\b")
_SUMMARY_RE = re.compile(
    r"(?i)(=+.*(?:failed|passed|error).*=+|"
    r"\d+\s+failed.*\d+\s+passed|"
    r"short test summary info|"
    r"Job failed|"
    r"Process completed with exit code)"
)
_FILE_FRAME_RE = re.compile(r'^\s*File "[^"]+", line \d+')
_JOB_HEADER_RE = re.compile(r"^---\s*Job:\s*.+")

# Dependency-checker style listings (must survive digest compression).
_MISSING_DEPS_HEADER_RE = re.compile(
    r"(?i)(?:CI REQUIREMENT TEST FAILED|Missing dependencies in requirements|"
    r"packages are imported in your code but missing|"
    r"Please add them to requirements)"
)
_DEP_BULLET_RE = re.compile(
    r"^\s*[•\*\-]\s*([A-Za-z0-9_.\-]+)\b(?:\s*\(imported in:([^)]*)\))?"
)


class ErrorBlock(TypedDict, total=False):
    kind: str  # traceback | pytest | lint | error_line | summary | tail
    text: str
    rank: int  # lower = more important


class LogReduceResult(TypedDict, total=False):
    digest: str
    relevant_errors: list[str]
    error_blocks: list[ErrorBlock]
    raw_chars: int
    digest_chars: int
    compression_ratio: float
    strategy: str


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False  # keep blank as structure (collapsed later)
    if _NOISE_LINE_RE.match(stripped):
        return True
    # Long base64 / hash-only lines
    if len(stripped) > 200 and re.fullmatch(r"[A-Za-z0-9+/=_\-]+", stripped):
        return True
    return False


def _collapse_blanks(lines: list[str]) -> list[str]:
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        out.append(line.rstrip())
    return out


def _collapse_duplicate_banners(lines: list[str]) -> list[str]:
    out: list[str] = []
    last_banner: str | None = None
    for line in lines:
        if _SECTION_BANNER_RE.match(line.strip()):
            key = re.sub(r"\s+", " ", line.strip())
            if key == last_banner:
                continue
            last_banner = key
            out.append(line)
            continue
        last_banner = None
        out.append(line)
    return out


def _extract_traceback_blocks(lines: list[str]) -> list[ErrorBlock]:
    blocks: list[ErrorBlock] = []
    i = 0
    while i < len(lines):
        if _TRACEBACK_START_RE.match(lines[i]):
            start = i
            i += 1
            while i < len(lines):
                line = lines[i]
                if (
                    _EXCEPTION_LINE_RE.match(line)
                    or line.strip().startswith(("During handling", "The above exception"))
                ):
                    # include exception line then stop (maybe continue one more if chained)
                    i += 1
                    if i < len(lines) and _TRACEBACK_START_RE.match(lines[i]):
                        continue  # chained traceback
                    break
                if _FILE_FRAME_RE.match(line) or line.startswith(("  ", "\t")) or not line.strip():
                    i += 1
                    continue
                # Non-traceback content — end block before this line
                break
            text = "\n".join(lines[start:i]).strip()
            if text:
                blocks.append({"kind": "traceback", "text": text, "rank": 0})
            continue
        i += 1
    return blocks


def _extract_pytest_blocks(lines: list[str]) -> list[ErrorBlock]:
    blocks: list[ErrorBlock] = []
    # Capture FAILED/ERROR headers + following E   lines
    i = 0
    while i < len(lines):
        if _PYTEST_FAILED_RE.match(lines[i].strip()):
            chunk = [lines[i]]
            i += 1
            while i < len(lines) and (
                _PYTEST_E_RE.match(lines[i]) or lines[i].startswith(" ") or not lines[i].strip()
            ):
                chunk.append(lines[i])
                i += 1
                if len(chunk) > 40:
                    break
            blocks.append({"kind": "pytest", "text": "\n".join(chunk).strip(), "rank": 1})
            continue
        if _PYTEST_E_RE.match(lines[i]):
            chunk = [lines[i]]
            i += 1
            while i < len(lines) and _PYTEST_E_RE.match(lines[i]):
                chunk.append(lines[i])
                i += 1
                if len(chunk) > 30:
                    break
            blocks.append({"kind": "pytest", "text": "\n".join(chunk).strip(), "rank": 1})
            continue
        i += 1
    return blocks


def _extract_deps_list_blocks(lines: list[str]) -> list[ErrorBlock]:
    """
    Keep dependency-checker bullet lists in the digest.

    Without this, only the headline 'Missing dependencies…' survives and the
    LLM invents packages from alias maps in checker source.
    """
    blocks: list[ErrorBlock] = []
    i = 0
    while i < len(lines):
        if not _MISSING_DEPS_HEADER_RE.search(lines[i]):
            i += 1
            continue
        chunk = [lines[i]]
        i += 1
        # Pull following explanatory + bullet lines
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                chunk.append(lines[i])
                i += 1
                if len(chunk) > 60:
                    break
                continue
            if _DEP_BULLET_RE.match(stripped) or _MISSING_DEPS_HEADER_RE.search(stripped):
                chunk.append(lines[i])
                i += 1
                continue
            if re.search(r"(?i)please add them|the following packages", stripped):
                chunk.append(lines[i])
                i += 1
                continue
            # Stop at next unrelated error/summary
            if (
                _EXCEPTION_LINE_RE.match(stripped)
                or _SUMMARY_RE.search(stripped)
                or _TRACEBACK_START_RE.match(stripped)
                or _PYTEST_FAILED_RE.match(stripped)
            ):
                break
            # One soft trailing line (e.g. blank instruction) then stop
            if len(chunk) <= 2 and len(stripped) < 200:
                chunk.append(lines[i])
                i += 1
                continue
            break
        text = "\n".join(chunk).strip()
        if text:
            blocks.append({"kind": "deps_list", "text": text, "rank": 1})
    return blocks


def _extract_lint_and_error_lines(lines: list[str]) -> list[ErrorBlock]:
    blocks: list[ErrorBlock] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in seen:
            continue
        if _LINT_FINDING_RE.search(stripped):
            seen.add(stripped)
            blocks.append({"kind": "lint", "text": stripped, "rank": 2})
        elif _DEP_BULLET_RE.match(stripped):
            seen.add(stripped)
            blocks.append({"kind": "deps_list", "text": stripped, "rank": 1})
        elif _EXCEPTION_LINE_RE.match(stripped) or (
            _ERROR_KEYWORD_RE.search(stripped) and not _WARNING_KEYWORD_RE.match(stripped)
            and len(stripped) < 400
        ):
            # Avoid re-adding traceback frames already covered
            if _FILE_FRAME_RE.match(stripped):
                continue
            if stripped.lower().startswith(("downloading", "collecting", "installing")):
                continue
            seen.add(stripped)
            blocks.append({"kind": "error_line", "text": stripped, "rank": 2})
        elif _SUMMARY_RE.search(stripped):
            seen.add(stripped)
            blocks.append({"kind": "summary", "text": stripped, "rank": 3})
    return blocks


def _job_segments(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split combined orchestrator logs into per-job segments when headers exist."""
    segments: list[tuple[str, list[str]]] = []
    current_name = "pipeline"
    current: list[str] = []
    for line in lines:
        if _JOB_HEADER_RE.match(line.strip()):
            if current:
                segments.append((current_name, current))
            current_name = line.strip()
            current = []
            continue
        current.append(line)
    if current or not segments:
        segments.append((current_name, current))
    return segments


def _dedupe_blocks(blocks: list[ErrorBlock]) -> list[ErrorBlock]:
    seen: set[str] = set()
    out: list[ErrorBlock] = []
    for block in blocks:
        key = re.sub(r"\s+", " ", (block.get("text") or "").strip())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(block)
    return out


def _tail_window(lines: list[str], n: int) -> ErrorBlock | None:
    if not lines:
        return None
    # Prefer starting from the last traceback / FAILED / ERROR marker inside the tail.
    start = max(0, len(lines) - n)
    window = lines[start:]
    anchor = 0
    for idx, line in enumerate(window):
        if (
            _TRACEBACK_START_RE.match(line)
            or _PYTEST_FAILED_RE.match(line.strip())
            or _EXCEPTION_LINE_RE.match(line)
            or re.search(r"(?i)\berror\b", line)
        ):
            anchor = idx
    text = "\n".join(window[anchor:]).strip()
    if not text:
        return None
    return {"kind": "tail", "text": text, "rank": 4}


def reduce_ci_logs(
    raw: str,
    *,
    max_chars: int | None = None,
    tail_lines: int | None = None,
    max_blocks: int | None = None,
) -> LogReduceResult:
    """
    Compress CI logs into an LLM-facing digest while listing discrete error blocks.

    Strategy:
      1. Strip ANSI / drop known noise lines
      2. Extract traceback, pytest, lint, and error/summary lines (all jobs)
      3. Always include a failure-biased tail window
      4. Rank, dedupe, and pack into max_chars
    """
    max_chars = max_chars or _env_int("CI_FIX_LOG_DIGEST_CHARS", DEFAULT_MAX_DIGEST_CHARS)
    tail_lines = tail_lines or _env_int("CI_FIX_LOG_TAIL_LINES", DEFAULT_TAIL_LINES)
    max_blocks = max_blocks or _env_int("CI_FIX_LOG_MAX_BLOCKS", DEFAULT_MAX_ERROR_BLOCKS)

    raw = raw or ""
    raw_chars = len(raw)
    cleaned = strip_ansi(raw)
    lines = cleaned.splitlines()

    # Drop noise early
    filtered = [ln for ln in lines if not _is_noise(ln)]
    filtered = _collapse_blanks(filtered)
    filtered = _collapse_duplicate_banners(filtered)

    blocks: list[ErrorBlock] = []
    for _job_name, segment in _job_segments(filtered):
        blocks.extend(_extract_traceback_blocks(segment))
        blocks.extend(_extract_pytest_blocks(segment))
        blocks.extend(_extract_deps_list_blocks(segment))
        blocks.extend(_extract_lint_and_error_lines(segment))

    tail = _tail_window(filtered, tail_lines)
    if tail:
        blocks.append(tail)

    blocks = _dedupe_blocks(blocks)
    blocks.sort(key=lambda b: (int(b.get("rank", 99)), -len(b.get("text") or "")))
    blocks = blocks[:max_blocks]

    # Pack digest: high-rank blocks first, then fill with remaining until cap
    parts: list[str] = []
    used = 0
    relevant: list[str] = []
    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        kind = block.get("kind") or "error"
        header = f"### {kind}"
        chunk = f"{header}\n{text}"
        # Avoid duplicating tail content that already appears in earlier blocks
        if kind == "tail" and any(text in (p or "") for p in parts):
            continue
        if used and used + len(chunk) + 2 > max_chars:
            # Try a truncated version of this block if nothing packed yet
            if not parts:
                remain = max_chars - len(header) - 2
                parts.append(f"{header}\n{text[:remain]}")
                relevant.append(text[:500])
            break
        parts.append(chunk)
        relevant.append(text if len(text) <= 800 else text[:800] + "…")
        used += len(chunk) + 2

    if not parts:
        # Absolute fallback: last N lines of filtered log
        fallback = "\n".join(filtered[-min(tail_lines, 80) :])
        digest = fallback[:max_chars]
        relevant = [digest] if digest.strip() else []
        strategy = "tail_fallback"
    else:
        digest = "\n\n".join(parts)
        if len(digest) > max_chars:
            digest = digest[:max_chars].rstrip() + "\n…(digest truncated)"
        strategy = "error_blocks+tail"

    digest_chars = len(digest)
    ratio = (digest_chars / raw_chars) if raw_chars else 1.0

    return LogReduceResult(
        digest=digest,
        relevant_errors=relevant,
        error_blocks=blocks,
        raw_chars=raw_chars,
        digest_chars=digest_chars,
        compression_ratio=round(ratio, 4),
        strategy=strategy,
    )


def logs_for_llm(state_or_logs: Any, raw_fallback: str = "") -> str:
    """
    Prefer `logs_digest` from graph state; otherwise reduce on the fly.

    Accepts a CIFixState-like mapping or a raw log string.
    """
    if isinstance(state_or_logs, dict):
        digest = state_or_logs.get("logs_digest")
        if isinstance(digest, str) and digest.strip():
            return digest
        raw = state_or_logs.get("logs") or raw_fallback or ""
        return reduce_ci_logs(str(raw)).get("digest") or str(raw)[:DEFAULT_MAX_DIGEST_CHARS]
    raw = str(state_or_logs or raw_fallback or "")
    return reduce_ci_logs(raw).get("digest") or raw[:DEFAULT_MAX_DIGEST_CHARS]
