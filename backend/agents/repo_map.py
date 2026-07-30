"""
Seeded, in-memory repo map for Axolotl CI repair.

Adapted from Aider's RepoMap idea (tree-sitter tags + PageRank), but scoped to
files already fetched via MCP — no local clone or disk tags cache.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict, namedtuple
from pathlib import Path
from typing import Iterable, Optional

from agents.patch_utils import normalize_patch_path

Tag = namedtuple("Tag", "rel_fname fname line name kind")

DEFAULT_MAP_MAX_FILES = 12
DEFAULT_MAP_TOKEN_BUDGET = 1800
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_STOP_IDENTS = {
    "the",
    "and",
    "for",
    "from",
    "import",
    "class",
    "def",
    "return",
    "none",
    "true",
    "false",
    "self",
    "this",
    "with",
    "file",
    "line",
    "error",
    "traceback",
    "module",
    "type",
    "name",
    "value",
    "test",
    "tests",
    "main",
    "init",
    "args",
    "kwargs",
    "print",
    "raise",
    "except",
    "while",
    "elif",
    "else",
    "pass",
    "null",
    "undefined",
}

_QUERY_PATH = Path(__file__).resolve().parent / "queries" / "python-tags.scm"
_parser_ready: Optional[bool] = None
_language = None
_parser = None
_query = None
_query_scm: Optional[str] = None


def map_max_files() -> int:
    try:
        return max(1, int(os.getenv("CI_FIX_MAP_MAX_FILES", str(DEFAULT_MAP_MAX_FILES))))
    except ValueError:
        return DEFAULT_MAP_MAX_FILES


def map_token_budget() -> int:
    try:
        return max(200, int(os.getenv("CI_FIX_MAP_TOKEN_BUDGET", str(DEFAULT_MAP_TOKEN_BUDGET))))
    except ValueError:
        return DEFAULT_MAP_TOKEN_BUDGET


def tree_sitter_available() -> bool:
    """Lazy-init tree-sitter; False means map features degrade gracefully."""
    global _parser_ready, _language, _parser, _query, _query_scm
    if _parser_ready is not None:
        return _parser_ready
    try:
        from tree_sitter import Query
        from tree_sitter_language_pack import get_language, get_parser

        if not _QUERY_PATH.exists():
            _parser_ready = False
            return False
        _query_scm = _QUERY_PATH.read_text(encoding="utf-8")
        _language = get_language("python")
        _parser = get_parser("python")
        _query = Query(_language, _query_scm)
        _parser_ready = True
        return True
    except Exception as exc:
        print(f"[RepoMap] tree-sitter unavailable ({exc}); map disabled")
        _parser_ready = False
        return False


def extract_idents_from_text(*texts: str) -> set[str]:
    """Pull identifier-like tokens from digests / root-cause text."""
    idents: set[str] = set()
    for text in texts:
        for match in _IDENT_RE.finditer(text or ""):
            token = match.group(1)
            if token.lower() in _STOP_IDENTS:
                continue
            if len(token) < 3:
                continue
            idents.add(token)
    return idents


def _run_captures(root_node):
    """Compatibility wrapper for tree-sitter Query APIs."""
    from tree_sitter import QueryCursor

    cursor = QueryCursor(_query)
    captures = cursor.captures(root_node)
    if isinstance(captures, dict):
        for tag, nodes in captures.items():
            for node in nodes:
                yield node, tag
        return

    # Older style: list[(node, tag)]
    for item in captures or []:
        if isinstance(item, tuple) and len(item) == 2:
            yield item[0], item[1]


def extract_tags(path: str, content: str) -> list[Tag]:
    """
    Extract definition/reference tags from one Python file's contents.

    Non-Python paths and parser failures return an empty list.
    """
    rel = normalize_patch_path(path)
    if not rel.lower().endswith((".py", ".pyi")):
        return []
    if not content or not tree_sitter_available():
        return []

    try:
        tree = _parser.parse(content.encode("utf-8", errors="replace"))
    except Exception:
        return []

    tags: list[Tag] = []
    saw_kinds: set[str] = set()
    try:
        for node, tag in _run_captures(tree.root_node):
            if tag.startswith("name.definition."):
                kind = "def"
            elif tag.startswith("name.reference."):
                kind = "ref"
            else:
                continue
            name = (node.text or b"").decode("utf-8", errors="replace")
            if not name:
                continue
            saw_kinds.add(kind)
            tags.append(
                Tag(
                    rel_fname=rel,
                    fname=rel,
                    line=int(node.start_point[0]),
                    name=name,
                    kind=kind,
                )
            )
    except Exception as exc:
        print(f"[RepoMap] tag extract failed for {rel}: {exc}")
        return []

    # If we only saw defs, backfill crude refs via identifier scan of callsites.
    if "def" in saw_kinds and "ref" not in saw_kinds:
        defined = {t.name for t in tags if t.kind == "def"}
        for match in _IDENT_RE.finditer(content):
            name = match.group(1)
            if name in defined:
                continue
            if name.lower() in _STOP_IDENTS:
                continue
            line = content.count("\n", 0, match.start())
            tags.append(Tag(rel_fname=rel, fname=rel, line=line, name=name, kind="ref"))

    return tags


def rank_neighbor_files(
    *,
    seed_files: Iterable[str],
    file_contents: dict[str, str],
    mentioned_idents: Optional[set[str]] = None,
    max_files: Optional[int] = None,
) -> list[str]:
    """
    Rank files by symbol connectivity to seed files / mentioned idents.

    Returns relative paths ordered most-relevant first (excluding pure seeds
    only when they have no tags — seeds still appear if ranked).
    """
    try:
        import networkx as nx
    except Exception:
        # Without networkx, fall back to seed order + remaining keys.
        seeds = [normalize_patch_path(p) for p in seed_files if p]
        others = [
            normalize_patch_path(p)
            for p in file_contents
            if normalize_patch_path(p) not in seeds
        ]
        ordered = list(dict.fromkeys(seeds + others))
        return ordered[: max_files or map_max_files()]

    seeds = {normalize_patch_path(p) for p in seed_files if p}
    idents = set(mentioned_idents or ())
    contents = {
        normalize_patch_path(path): content
        for path, content in (file_contents or {}).items()
        if content is not None
    }
    if not contents:
        return []

    defines: dict[str, set[str]] = defaultdict(set)
    references: dict[str, list[str]] = defaultdict(list)
    personalization: dict[str, float] = {}
    personalize = 100 / max(1, len(contents))

    for rel, content in contents.items():
        current_pers = 0.0
        if rel in seeds:
            current_pers += personalize
        path_bits = set(Path(rel).parts) | {
            Path(rel).name,
            Path(rel).stem,
        }
        if path_bits.intersection(idents):
            current_pers += personalize
        if current_pers > 0:
            personalization[rel] = current_pers

        for tag in extract_tags(rel, content):
            if tag.kind == "def":
                defines[tag.name].add(rel)
            elif tag.kind == "ref":
                references[tag.name].append(rel)

    if not references and defines:
        references = {name: list(files) for name, files in defines.items()}

    shared = set(defines).intersection(references)
    graph = nx.MultiDiGraph()

    for ident, definers in defines.items():
        if ident in references:
            continue
        for definer in definers:
            graph.add_edge(definer, definer, weight=0.1, ident=ident)

    for ident in shared:
        mul = 1.0
        is_snake = ("_" in ident) and any(c.isalpha() for c in ident)
        is_camel = any(c.isupper() for c in ident) and any(c.islower() for c in ident)
        if ident in idents:
            mul *= 10
        if (is_snake or is_camel) and len(ident) >= 8:
            mul *= 10
        if ident.startswith("_"):
            mul *= 0.1
        if len(defines[ident]) > 5:
            mul *= 0.1

        for referencer, num_refs in Counter(references[ident]).items():
            for definer in defines[ident]:
                use_mul = mul * (50 if referencer in seeds else 1)
                graph.add_edge(
                    referencer,
                    definer,
                    weight=use_mul * math.sqrt(num_refs),
                    ident=ident,
                )

    if graph.number_of_nodes() == 0:
        ordered = list(dict.fromkeys(list(seeds) + list(contents)))
        return ordered[: max_files or map_max_files()]

    pers_args = (
        {"personalization": personalization, "dangling": personalization}
        if personalization
        else {}
    )
    try:
        ranked = nx.pagerank(graph, weight="weight", **pers_args)
    except Exception:
        try:
            ranked = nx.pagerank(graph, weight="weight")
        except Exception:
            ordered = list(dict.fromkeys(list(seeds) + list(contents)))
            return ordered[: max_files or map_max_files()]

    # Prefer non-seed neighbors first, then seeds, by PageRank.
    ranked_files = sorted(ranked.items(), key=lambda item: item[1], reverse=True)
    neighbors = [path for path, _ in ranked_files if path not in seeds]
    seed_ordered = [path for path, _ in ranked_files if path in seeds]
    leftover = [path for path in contents if path not in ranked]
    ordered = list(dict.fromkeys(neighbors + seed_ordered + leftover))
    limit = max_files or map_max_files()
    return ordered[:limit]


def _estimate_tokens(text: str) -> int:
    # Rough 4-char heuristic — good enough for map budget trimming.
    return max(1, len(text) // 4)


def render_repo_map(
    *,
    file_contents: dict[str, str],
    ranked_files: list[str],
    seed_files: Optional[Iterable[str]] = None,
    mentioned_idents: Optional[set[str]] = None,
    token_budget: Optional[int] = None,
) -> str:
    """
    Render a compact symbol map for LLM context.

    Format:
        path/to/file.py:
          def process_data
          class Worker
          process_data()  # ref
    """
    budget = token_budget or map_token_budget()
    seeds = {normalize_patch_path(p) for p in (seed_files or []) if p}
    idents = set(mentioned_idents or ())
    lines: list[str] = []
    used = 0

    for path in ranked_files:
        rel = normalize_patch_path(path)
        content = file_contents.get(rel)
        if content is None:
            continue
        tags = extract_tags(rel, content)
        if not tags and rel not in seeds:
            continue

        block = [f"{rel}:"]
        shown: set[tuple[str, str]] = set()
        # Prefer defs matching mentioned idents, then other defs, then refs.
        ordered_tags = sorted(
            tags,
            key=lambda t: (
                0 if t.kind == "def" and t.name in idents else 1 if t.kind == "def" else 2,
                t.line,
                t.name,
            ),
        )
        for tag in ordered_tags:
            key = (tag.kind, tag.name)
            if key in shown:
                continue
            shown.add(key)
            if tag.kind == "def":
                block.append(f"  def {tag.name}")
            else:
                if tag.name not in idents and len(shown) > 8:
                    continue
                block.append(f"  ref {tag.name}")
            if len(block) > 12:
                break

        if len(block) == 1:
            block.append("  (file)")

        chunk = "\n".join(block) + "\n"
        cost = _estimate_tokens(chunk)
        if used + cost > budget and lines:
            break
        lines.append(chunk.rstrip("\n"))
        used += cost

    if not lines:
        return ""
    header = "Repository symbol map (seeded / partial):\n"
    return header + "\n".join(lines)


def high_confidence_neighbors(
    *,
    ranked_files: list[str],
    seed_files: Iterable[str],
    file_contents: dict[str, str],
    mentioned_idents: set[str],
    max_merge: int = 6,
) -> list[str]:
    """
    Files that define or reference a mentioned failing symbol — safe to merge
    into the expanded worklist.
    """
    seeds = {normalize_patch_path(p) for p in seed_files if p}
    if not mentioned_idents:
        return []

    out: list[str] = []
    for path in ranked_files:
        rel = normalize_patch_path(path)
        if rel in seeds:
            continue
        content = file_contents.get(rel)
        if not content:
            continue
        tags = extract_tags(rel, content)
        names = {t.name for t in tags}
        if names.intersection(mentioned_idents):
            out.append(rel)
        if len(out) >= max_merge:
            break
    return out


def build_repo_map(
    *,
    seed_files: Iterable[str],
    file_contents: dict[str, str],
    mentioned_idents: Optional[set[str]] = None,
    max_files: Optional[int] = None,
    token_budget: Optional[int] = None,
) -> tuple[str, list[str]]:
    """
    Convenience: rank + render.

    Returns (repo_map_text, ranked_neighbor_files).
    """
    idents = set(mentioned_idents or ())
    ranked = rank_neighbor_files(
        seed_files=seed_files,
        file_contents=file_contents,
        mentioned_idents=idents,
        max_files=max_files,
    )
    text = render_repo_map(
        file_contents=file_contents,
        ranked_files=ranked,
        seed_files=seed_files,
        mentioned_idents=idents,
        token_budget=token_budget,
    )
    return text, ranked
