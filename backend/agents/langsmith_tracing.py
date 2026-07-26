"""
LangSmith tracing helpers for the LangGraph CI fix agent.

Enable with:
  LANGSMITH_TRACING=true
  LANGSMITH_API_KEY=lsv2_...
  LANGSMITH_PROJECT=axolotl-ci-fix   (optional; default: axolotl-ci-fix)

Legacy LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT are also honored.
"""

from __future__ import annotations

import os
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_langsmith_enabled() -> bool:
    """Return True when tracing is turned on and an API key is present."""
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    tracing = _env_bool("LANGSMITH_TRACING") or _env_bool("LANGCHAIN_TRACING_V2")
    return bool(tracing and api_key)


def configure_langsmith() -> bool:
    """
    Normalize LangSmith env vars so LangChain/LangGraph auto-trace.

    Safe to call multiple times. Returns whether tracing is active.
    """
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    tracing = _env_bool("LANGSMITH_TRACING") or _env_bool("LANGCHAIN_TRACING_V2")
    project = (
        os.getenv("LANGSMITH_PROJECT")
        or os.getenv("LANGCHAIN_PROJECT")
        or "axolotl-ci-fix"
    )
    endpoint = os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")

    if not tracing:
        print("[LangSmith] Tracing off (set LANGSMITH_TRACING=true to enable)")
        return False

    if not api_key:
        print("[LangSmith] Tracing requested but LANGSMITH_API_KEY is missing — disabled")
        return False

    # Canonical modern vars
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project

    # Legacy aliases still read by some LangChain versions
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project

    if endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    print(f"[LangSmith] Tracing enabled → project={project}")
    return True


def build_run_config(
    *,
    pipeline_id: str,
    project_id: str,
    branch: str,
    validate_enabled: bool,
) -> dict[str, Any]:
    """RunnableConfig-style dict for graph.ainvoke (tags + metadata for LangSmith)."""
    return {
        "run_name": f"ci-fix-{pipeline_id}",
        "tags": ["axolotl", "ci-fix", "langgraph"],
        "metadata": {
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "branch": branch,
            "validate_enabled": validate_enabled,
            "service": "axolotl",
        },
    }
