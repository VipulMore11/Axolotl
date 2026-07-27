"""
Advanced code-surgery patch engine (Aider/RooCode style).

Applies LLM-generated Search/Replace blocks to real file contents with three
subsystems that keep patches from failing on hallucinated formatting:

  A. Middle-out search — candidate windows are scanned outward from a line
     hint (extracted from the CI stack trace) instead of top-to-bottom, using
     Levenshtein-distance fuzzy matching to locate the search block.
  B. Relative indentation preservation — the matched file lines' leading
     whitespace is captured and the replace block is re-indented relative to
     it, so mixed tabs / 2-space / 4-space hallucinations don't leak in.
  C. Rich diagnostic feedback — on failure, difflib finds the closest real
     lines so the LLM can be asked to fix ONLY the failed block while already
     applied blocks stay cached.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

# Similarity (1 - normalized Levenshtein distance) required to accept a fuzzy match.
DEFAULT_FUZZY_THRESHOLD = 0.85
# Fuzzy score at which the middle-out scan stops early.
_EARLY_EXIT_SIMILARITY = 0.98
# Character cap per side for Levenshtein scoring (keeps worst case bounded).
_LEV_CHAR_CAP = 1500


# ── Line hints (subsystem A input) ──────────────────────────────────


_PY_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
# lint/compiler style: path/to/file.py:12:5 or file.js:12
_PATH_LINE_RE = re.compile(
    r"(?<![\w:/])((?:[A-Za-z]:)?[\w.\-]+(?:[/\\][\w.\-]+)*\.[A-Za-z]\w{0,9}):(\d+)(?::\d+)?"
)


def normalize_patch_path(path: str) -> str:
    cleaned = (path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


_normalize_path = normalize_patch_path


def extract_line_hints(logs: str) -> dict[str, int]:
    """
    Pull `file -> line number` hints out of CI logs / stack traces.

    Later occurrences win: in a Python traceback the last frame is the error
    site, and lint output lists the offending line per finding.
    """
    hints: dict[str, int] = {}
    for match in _PY_FRAME_RE.finditer(logs or ""):
        hints[_normalize_path(match.group(1))] = int(match.group(2))
    for match in _PATH_LINE_RE.finditer(logs or ""):
        hints[_normalize_path(match.group(1))] = int(match.group(2))
    return hints


def line_hint_for(hints: dict[str, int], file_path: str) -> Optional[int]:
    """Look up a hint by exact path, suffix overlap, then basename."""
    if not hints:
        return None
    path = _normalize_path(file_path)
    if path in hints:
        return hints[path]
    for known, line in hints.items():
        if known.endswith("/" + path) or path.endswith("/" + known):
            return line
    basename = path.rsplit("/", 1)[-1]
    for known, line in hints.items():
        if known.rsplit("/", 1)[-1] == basename:
            return line
    return None


# ── Fuzzy matching primitives ───────────────────────────────────────


def _levenshtein(a: str, b: str) -> int:
    """Iterative two-row Levenshtein distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    previous = list(range(len(a) + 1))
    for j, ch_b in enumerate(b, start=1):
        current = [j]
        for i, ch_a in enumerate(a, start=1):
            cost = 0 if ch_a == ch_b else 1
            current.append(min(previous[i] + 1, current[i - 1] + 1, previous[i - 1] + cost))
        previous = current
    return previous[-1]


def levenshtein_similarity(a: str, b: str) -> float:
    """1.0 for identical strings, 0.0 for entirely different."""
    a, b = a[:_LEV_CHAR_CAP], b[:_LEV_CHAR_CAP]
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - (_levenshtein(a, b) / longest)


def _middle_out_order(candidate_count: int, epicenter: int) -> list[int]:
    """Window start indices ordered by distance from the epicenter line."""
    epicenter = max(0, min(epicenter, candidate_count - 1))
    return sorted(range(candidate_count), key=lambda start: (abs(start - epicenter), start))


# ── Indentation preservation (subsystem B) ──────────────────────────


def _leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _first_nonblank_indent(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return _leading_whitespace(line)
    return ""


def _infer_indent_units(indent_map: dict[str, str]) -> Optional[tuple[str, str]]:
    """
    Derive one indentation level in the LLM's style and the file's style from
    two mapped nesting levels (e.g. '  ' -> '\t' means 2 spaces per tab).
    """
    pairs = sorted(indent_map.items(), key=lambda kv: len(kv[0]))
    for (llm_a, file_a), (llm_b, file_b) in zip(pairs, pairs[1:]):
        if llm_b.startswith(llm_a) and len(llm_b) > len(llm_a) and file_b.startswith(file_a):
            llm_unit = llm_b[len(llm_a):]
            file_unit = file_b[len(file_a):]
            if llm_unit:
                return llm_unit, file_unit
    return None


def reindent_replace_block(
    matched_file_lines: list[str],
    search_lines: list[str],
    replace_lines: list[str],
) -> list[str]:
    """
    Rebuild the replace block using the original file's indentation style.

    The search block and the matched file lines describe the same code in two
    styles, which gives a per-level mapping from the LLM's whitespace to the
    file's real whitespace. Replace lines are rewritten through that mapping;
    levels the search block never showed are scaled by the inferred indent
    unit relative to the block's first line.
    """
    file_indents = [_leading_whitespace(l) for l in matched_file_lines if l.strip()]
    llm_indents = [_leading_whitespace(l) for l in search_lines if l.strip()]

    indent_map: dict[str, str] = {}
    for llm_ws, file_ws in zip(llm_indents, file_indents):
        indent_map.setdefault(llm_ws, file_ws)

    if all(llm_ws == file_ws for llm_ws, file_ws in indent_map.items()):
        return list(replace_lines)

    base_llm = llm_indents[0] if llm_indents else ""
    base_file = file_indents[0] if file_indents else ""
    units = _infer_indent_units(indent_map)

    rebuilt: list[str] = []
    for line in replace_lines:
        if not line.strip():
            rebuilt.append("")
            continue
        ws = _leading_whitespace(line)
        body = line.lstrip()

        if ws in indent_map:
            rebuilt.append(indent_map[ws] + body)
            continue

        delta = len(ws) - len(base_llm)
        if delta < 0:
            # Dedented below the block base (e.g. closing a scope).
            rebuilt.append(base_file[: max(0, len(base_file) + delta)] + body)
        elif units is not None:
            llm_unit, file_unit = units
            depth = delta // max(1, len(llm_unit))
            rebuilt.append(base_file + file_unit * depth + body)
        elif ws.startswith(base_llm):
            rebuilt.append(base_file + ws[len(base_llm):] + body)
        else:
            rebuilt.append(base_file + body)
    return rebuilt


# ── Patch application (subsystems A + B) ────────────────────────────


@dataclass
class PatchResult:
    """Outcome of applying one Search/Replace block."""

    success: bool
    content: str = ""
    error: str = ""
    nearest_match: str = ""
    match_line: int = -1  # 1-based first line of the matched window
    similarity: float = 0.0


def _window_text(lines: list[str], start: int, size: int) -> str:
    return "\n".join(lines[start : start + size])


def _find_block(
    file_lines: list[str],
    search_lines: list[str],
    line_hint: Optional[int],
    threshold: float,
) -> tuple[int, float]:
    """
    Locate `search_lines` in `file_lines` and return (start_index, similarity),
    or (-1, best_similarity) when nothing clears the threshold.

    Middle-out: candidates are tried by distance from the hint line so the
    correct region of large files is reached first; ties (e.g. duplicated
    code) resolve to the occurrence nearest the failure site.
    """
    size = len(search_lines)
    candidate_count = len(file_lines) - size + 1
    if candidate_count <= 0:
        return -1, 0.0

    epicenter = (line_hint - 1) if line_hint else candidate_count // 2
    order = _middle_out_order(candidate_count, epicenter)
    search_text = "\n".join(search_lines)

    # Pass 1: exact match.
    for start in order:
        if _window_text(file_lines, start, size) == search_text:
            return start, 1.0

    # Pass 2: trailing-whitespace-insensitive match.
    stripped_search = [line.rstrip() for line in search_lines]
    for start in order:
        if [l.rstrip() for l in file_lines[start : start + size]] == stripped_search:
            return start, 1.0

    # Pass 3: Levenshtein fuzzy scan, cheap difflib prefilter first.
    best_start, best_score = -1, 0.0
    prefilter_floor = max(0.0, threshold - 0.15)
    for start in order:
        window = _window_text(file_lines, start, size)
        quick = difflib.SequenceMatcher(None, window, search_text)
        if quick.real_quick_ratio() < prefilter_floor or quick.quick_ratio() < prefilter_floor:
            continue
        score = levenshtein_similarity(window, search_text)
        if score > best_score:
            best_start, best_score = start, score
            if score >= _EARLY_EXIT_SIMILARITY:
                break

    if best_score >= threshold:
        return best_start, best_score
    return -1, best_score


def apply_fuzzy_patch(
    original: str,
    search_block: str,
    replace_block: str,
    line_hint: Optional[int] = None,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> PatchResult:
    """
    Apply one Search/Replace block to `original` file content.

    An empty search_block means file creation: it succeeds only when the
    original content is empty, with the replace block as the whole file.
    """
    if not search_block.strip():
        if not original.strip():
            return PatchResult(success=True, content=replace_block, similarity=1.0, match_line=1)
        return PatchResult(
            success=False,
            error=(
                "SEARCH block is empty but the file already has content. "
                "Empty search blocks are only valid for creating new files."
            ),
        )

    file_lines = original.splitlines()
    search_lines = search_block.splitlines()
    # Ignore leading/trailing blank lines the LLM may pad the block with.
    while search_lines and not search_lines[0].strip():
        search_lines.pop(0)
    while search_lines and not search_lines[-1].strip():
        search_lines.pop()
    if not search_lines:
        return PatchResult(success=False, error="SEARCH block contains only blank lines.")

    start, score = _find_block(file_lines, search_lines, line_hint, threshold)
    if start < 0:
        return PatchResult(
            success=False,
            error=f"SEARCH block failed to match (best similarity {score:.2f} < {threshold:.2f}).",
            nearest_match=find_nearest_match(original, "\n".join(search_lines)),
            similarity=score,
        )

    matched_lines = file_lines[start : start + len(search_lines)]
    replace_lines = reindent_replace_block(
        matched_lines, search_lines, replace_block.splitlines()
    )
    updated_lines = file_lines[:start] + replace_lines + file_lines[start + len(search_lines):]

    updated = "\n".join(updated_lines)
    if original.endswith("\n") and not updated.endswith("\n"):
        updated += "\n"
    return PatchResult(
        success=True,
        content=updated,
        match_line=start + 1,
        similarity=score,
    )


# ── Rich diagnostics (subsystem C) ──────────────────────────────────


def find_nearest_match(original: str, search_block: str, context: int = 0) -> str:
    """
    Return the line-numbered window of the original file that most closely
    resembles the failed search block (difflib.SequenceMatcher scoring).
    """
    file_lines = original.splitlines()
    search_lines = [l for l in search_block.splitlines() if l.strip()] or [""]
    if not file_lines:
        return "(file is empty)"

    size = min(max(len(search_lines), 1), 10)
    search_text = "\n".join(search_lines)
    best_start, best_score = 0, -1.0
    for start in range(max(1, len(file_lines) - size + 1)):
        score = difflib.SequenceMatcher(
            None, _window_text(file_lines, start, size), search_text
        ).ratio()
        if score > best_score:
            best_start, best_score = start, score

    lo = max(0, best_start - context)
    hi = min(len(file_lines), best_start + size + context)
    return "\n".join(f"{i + 1:5d}| {file_lines[i]}" for i in range(lo, hi))


def build_block_failure_feedback(
    *,
    file_path: str,
    error: str,
    nearest_match: str,
    applied_count: int,
    total_count: int,
) -> str:
    """Targeted error prompt for partial retries (TRD subsystem C)."""
    return (
        f"Error: SEARCH block failed to match in `{file_path}`. {error}\n"
        f"Did you mean to target these actual lines?\n{nearest_match or '(no similar lines found)'}\n"
        f"Note: {applied_count} of {total_count} blocks applied successfully. "
        "Do not resend them. Reply ONLY with the fixed version of the failed block "
        "(same file_path; search_block copied EXACTLY from the lines above, "
        "without the line-number prefixes)."
    )


# ── Multi-block application with block cache ────────────────────────


@dataclass
class BlockApplication:
    """Result of applying an ordered list of blocks to a set of files."""

    contents: dict[str, str] = field(default_factory=dict)
    applied: list[dict[str, str]] = field(default_factory=list)
    failed: list[tuple[dict[str, str], PatchResult]] = field(default_factory=list)


def apply_blocks(
    blocks: list[dict[str, str]],
    working_contents: dict[str, str],
    line_hints: Optional[dict[str, int]] = None,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> BlockApplication:
    """
    Apply Search/Replace blocks in order against `working_contents`
    (file_path -> current content; missing keys are treated as new files).

    Successful blocks mutate the returned contents (the cache); failures are
    collected with their diagnostics so callers can retry only those blocks.
    """
    result = BlockApplication(contents=dict(working_contents))
    hints = line_hints or {}
    for block in blocks:
        path = _normalize_path(str(block.get("file_path") or ""))
        if not path:
            result.failed.append((block, PatchResult(success=False, error="Missing file_path.")))
            continue
        original = result.contents.get(path, "")
        patch = apply_fuzzy_patch(
            original,
            str(block.get("search_block") or ""),
            str(block.get("replace_block") or ""),
            line_hint=line_hint_for(hints, path),
            threshold=threshold,
        )
        if patch.success:
            result.contents[path] = patch.content
            result.applied.append(block)
        else:
            result.failed.append((block, patch))
    return result
