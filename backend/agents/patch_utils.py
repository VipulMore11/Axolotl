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
  C. Safe delta transfer — approximate matches receive only the intended
     SEARCH→REPLACE delta; unrelated current-source divergence is preserved,
     while overlapping drift and partial application are rejected atomically.
  D. Rich diagnostic feedback — on failure, difflib finds the closest real
     lines so the LLM can be asked to fix ONLY the failed block while already
     applied blocks stay cached.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from diff_match_patch import diff_match_patch

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


def _relative_indent_signature(lines: list[str]) -> tuple[tuple[str, str], ...]:
    """
    Represent indentation as transitions between adjacent nonblank lines.

    Absolute indentation on the first line is intentionally ignored. This is
    the production-sized part of Aider's RelativeIndenter idea: blocks nested
    at different levels still compare exactly when their relative structure
    and code are identical.
    """
    signature: list[tuple[str, str]] = []
    previous = ""
    initialized = False
    for line in lines:
        body = line.lstrip()
        indent = line[: len(line) - len(body)]
        if not body.strip():
            signature.append(("", ""))
            continue
        if not initialized:
            transition = ""
            initialized = True
        elif indent.startswith(previous):
            transition = "+" + indent[len(previous) :]
        elif previous.startswith(indent):
            transition = "-" * (len(previous) - len(indent))
        else:
            # Non-nesting whitespace switch (usually tabs vs spaces).
            transition = "=" + indent
        signature.append((transition, body.rstrip()))
        previous = indent
    return tuple(signature)


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
    strategy: str = ""


def _window_text(lines: list[str], start: int, size: int) -> str:
    return "\n".join(lines[start : start + size])


def _find_block(
    file_lines: list[str],
    search_lines: list[str],
    line_hint: Optional[int],
    threshold: float,
) -> tuple[int, float, str]:
    """
    Locate `search_lines` and return (start_index, similarity, strategy).

    Exact/normalized duplicate matches without a line hint are rejected as
    ambiguous rather than silently editing an arbitrary occurrence.

    Middle-out: candidates are tried by distance from the hint line so the
    correct region of large files is reached first; ties (e.g. duplicated
    code) resolve to the occurrence nearest the failure site.
    """
    size = len(search_lines)
    candidate_count = len(file_lines) - size + 1
    if candidate_count <= 0:
        return -1, 0.0, "not_found"

    epicenter = (line_hint - 1) if line_hint else candidate_count // 2
    order = _middle_out_order(candidate_count, epicenter)
    search_text = "\n".join(search_lines)

    def choose(starts: list[int], strategy: str) -> tuple[int, float, str]:
        if not starts:
            return -1, 0.0, strategy
        if len(starts) > 1 and line_hint is None:
            return -1, 1.0, f"ambiguous_{strategy}"
        return min(starts, key=order.index), 1.0, strategy

    # Pass 1: exact match.
    exact = [
        start
        for start in order
        if _window_text(file_lines, start, size) == search_text
    ]
    if exact:
        return choose(exact, "exact")

    # Pass 2: trailing-whitespace-insensitive match.
    stripped_search = [line.rstrip() for line in search_lines]
    whitespace = [
        start
        for start in order
        if [line.rstrip() for line in file_lines[start : start + size]]
        == stripped_search
    ]
    if whitespace:
        return choose(whitespace, "whitespace")

    # Pass 3: exact code/relative-indentation structure.
    relative_search = _relative_indent_signature(search_lines)
    relative = [
        start
        for start in order
        if _relative_indent_signature(file_lines[start : start + size])
        == relative_search
    ]
    if relative:
        return choose(relative, "relative_indent")

    # Pass 4: Levenshtein candidate discovery, cheap prefilter first.
    best_start, best_score = -1, 0.0
    accepted: list[tuple[int, float]] = []
    prefilter_floor = max(0.0, threshold - 0.15)
    for start in order:
        window = _window_text(file_lines, start, size)
        quick = difflib.SequenceMatcher(None, window, search_text)
        if quick.real_quick_ratio() < prefilter_floor or quick.quick_ratio() < prefilter_floor:
            continue
        score = levenshtein_similarity(window, search_text)
        if score >= threshold:
            accepted.append((start, score))
        if score > best_score:
            best_start, best_score = start, score
            if line_hint is not None and score >= _EARLY_EXIT_SIMILARITY:
                break

    if best_score >= threshold:
        if line_hint is None:
            near_best = [
                start
                for start, score in accepted
                if best_score - score <= 0.01
            ]
            if len(near_best) > 1:
                return -1, best_score, "ambiguous_fuzzy"
        return best_start, best_score, "fuzzy_delta"
    return -1, best_score, "not_found"


def _protected_divergent_lines(
    search_lines: list[str],
    replace_lines: list[str],
    matched_lines: list[str],
) -> Counter[str]:
    """
    Capture current-source lines outside the LLM's intended edit.

    If SEARCH→REPLACE leaves a line unchanged but the real source has diverged
    there, delta transfer must preserve the real line. This postcondition is
    what prevents a fuzzy match from erasing concurrent/unrelated edits.
    """
    search_bodies = [line.rstrip() for line in search_lines]
    replace_bodies = [line.rstrip() for line in replace_lines]
    matcher = difflib.SequenceMatcher(
        None, search_bodies, replace_bodies, autojunk=False
    )
    protected: Counter[str] = Counter()
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for index in range(i1, min(i2, len(matched_lines))):
            actual = matched_lines[index]
            if actual.rstrip() != search_lines[index].rstrip():
                protected[actual] += 1
    return protected


def _apply_fuzzy_delta(
    matched_lines: list[str],
    search_lines: list[str],
    replace_lines: list[str],
) -> tuple[Optional[list[str]], str]:
    """
    Transfer only the SEARCH→REPLACE delta onto the matched current source.

    Unlike blind whole-window replacement, this preserves unrelated drift in
    the current file. Every diff-match-patch hunk must apply, and unchanged
    divergent lines are enforced as an atomic postcondition.
    """
    aligned_search = reindent_replace_block(
        matched_lines, search_lines, search_lines
    )
    aligned_replace = reindent_replace_block(
        matched_lines, search_lines, replace_lines
    )
    intent = difflib.SequenceMatcher(
        None,
        [line.rstrip() for line in aligned_search],
        [line.rstrip() for line in aligned_replace],
        autojunk=False,
    )
    for tag, i1, i2, _j1, _j2 in intent.get_opcodes():
        if tag == "equal":
            continue
        # Inserts do not consume current-source lines and cannot overlap drift.
        if i1 == i2:
            continue
        expected = [line.rstrip() for line in aligned_search[i1:i2]]
        actual = [line.rstrip() for line in matched_lines[i1:i2]]
        if expected != actual:
            return None, (
                "The current source diverged inside the lines this patch would "
                "modify; refusing an unsafe fuzzy overwrite. Regenerate SEARCH "
                "from the latest file contents."
            )

    search_text = "\n".join(aligned_search)
    replace_text = "\n".join(aligned_replace)
    matched_text = "\n".join(matched_lines)

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 2
    dmp.Match_Threshold = 0.35
    dmp.Match_Distance = max(100, len(matched_text))
    diff = dmp.diff_main(search_text, replace_text, None)
    dmp.diff_cleanupSemantic(diff)
    patches = dmp.patch_make(search_text, diff)
    transferred, applied = dmp.patch_apply(patches, matched_text)
    if not all(applied):
        return None, "Aider-style delta transfer could not apply every edit atomically."

    transferred_lines = transferred.splitlines()
    protected = _protected_divergent_lines(
        aligned_search, aligned_replace, matched_lines
    )
    remaining = Counter(transferred_lines)
    lost = protected - remaining
    if lost:
        examples = ", ".join(repr(line) for line in list(lost)[:3])
        return None, (
            "Delta transfer would overwrite unrelated current-source changes "
            f"({examples}); regenerate SEARCH from the latest file contents."
        )
    return transferred_lines, ""


def _newline_style(text: str) -> str:
    """Preserve the file's dominant line-ending convention."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


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

    start, score, strategy = _find_block(
        file_lines, search_lines, line_hint, threshold
    )
    if start < 0:
        if strategy.startswith("ambiguous_"):
            error = (
                "SEARCH block matches multiple locations and no CI line hint "
                "disambiguates them. Include more unique surrounding context."
            )
        else:
            error = (
                f"SEARCH block failed to match (best similarity {score:.2f} "
                f"< {threshold:.2f})."
            )
        return PatchResult(
            success=False,
            error=error,
            nearest_match=find_nearest_match(original, "\n".join(search_lines)),
            similarity=score,
            strategy=strategy,
        )

    matched_lines = file_lines[start : start + len(search_lines)]
    raw_replace_lines = replace_block.splitlines()
    if strategy == "fuzzy_delta":
        replace_lines, delta_error = _apply_fuzzy_delta(
            matched_lines, search_lines, raw_replace_lines
        )
        if replace_lines is None:
            return PatchResult(
                success=False,
                error=delta_error,
                nearest_match=find_nearest_match(
                    original, "\n".join(search_lines)
                ),
                match_line=start + 1,
                similarity=score,
                strategy=strategy,
            )
    else:
        replace_lines = reindent_replace_block(
            matched_lines, search_lines, raw_replace_lines
        )
    updated_lines = file_lines[:start] + replace_lines + file_lines[start + len(search_lines):]

    newline = _newline_style(original)
    updated = newline.join(updated_lines)
    if original.endswith(("\n", "\r")) and not updated.endswith(newline):
        updated += newline
    return PatchResult(
        success=True,
        content=updated,
        match_line=start + 1,
        similarity=score,
        strategy=strategy,
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
