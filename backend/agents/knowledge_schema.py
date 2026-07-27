"""
Knowledge Base schema for Axolotl CI-fix memory.

Nodes and edges form a provenance graph across pipeline sessions, persisted in
Neo4j. Each node carries the shared `:KBNode` label plus its type label; each
edge becomes a relationship of the matching type.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypedDict


class NodeType(str, Enum):
    ENTITY = "Entity"  # files, libraries, dependencies
    CLAIM = "Claim"  # diagnosed root_cause
    SOURCE = "Source"  # CI log / pipeline_id
    ARTIFACT = "Artifact"  # FixProposal / file patches
    RUN = "Run"  # LangGraph execution record


class EdgeType(str, Enum):
    MENTIONS = "mentions"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"


class KBNode(TypedDict, total=False):
    node_id: str
    type: str
    label: str
    properties: dict[str, Any]
    project_id: str
    created_at: str


class KBEdge(TypedDict, total=False):
    edge_id: str
    type: str
    from_id: str
    to_id: str
    properties: dict[str, Any]
    created_at: str


class HistoricalFixContext(TypedDict, total=False):
    """Context injected into requirements_analysis for graph grounding."""

    claim_label: str
    claim_id: str
    artifact_summary: str
    artifact_patches: list[dict[str, str]]
    commit_message: str
    pipeline_id: str
    score_hint: str
