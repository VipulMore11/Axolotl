"""
Neo4j-backed Knowledge Base store for CI-fix provenance.

Async reads/writes; used for:
  - Graph grounding during requirements_analysis (read)
  - Post-HITL extraction after MR approval/merge (write, additive + supersedes)

Every node carries the shared `:KBNode` label plus its type label
(`:Claim`, `:Artifact`, `:Entity`, `:Run`, `:Source`) so a single uniqueness
constraint on `node_id` covers the whole graph.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, UTC
from typing import Any, Optional

from agents.knowledge_schema import (
    EdgeType,
    HistoricalFixContext,
    NodeType,
)
from db.neo4j_service import (
    CLAIM_FULLTEXT_INDEX,
    Neo4jService,
    decode_properties,
    encode_properties,
    get_neo4j_service,
)

# Cypher cannot parameterize labels or relationship types, so both are resolved
# from closed enums to literals that are safe to interpolate.
_NODE_LABELS: dict[str, str] = {
    NodeType.ENTITY.value: "Entity",
    NodeType.CLAIM.value: "Claim",
    NodeType.SOURCE.value: "Source",
    NodeType.ARTIFACT.value: "Artifact",
    NodeType.RUN.value: "Run",
}

_EDGE_RELS: dict[str, str] = {
    EdgeType.MENTIONS.value: "MENTIONS",
    EdgeType.SUPPORTS.value: "SUPPORTS",
    EdgeType.CONTRADICTS.value: "CONTRADICTS",
    EdgeType.DERIVED_FROM.value: "DERIVED_FROM",
    EdgeType.SUPERSEDES.value: "SUPERSEDES",
}

_LUCENE_SPECIALS = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(text: str, n: int = 48) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", (text or "").strip().lower())
    return (cleaned[:n] or "unknown").strip("_")


def _claim_id(project_id: str, root_cause: str) -> str:
    digest = hashlib.sha1(f"{project_id}|{root_cause}".encode("utf-8")).hexdigest()[:16]
    return f"claim:{_slug(project_id, 24)}:{digest}"


def _node_label(node_type: NodeType | str) -> str:
    key = node_type.value if isinstance(node_type, NodeType) else str(node_type)
    label = _NODE_LABELS.get(key)
    if label is None:
        raise ValueError(f"Unknown KB node type: {key}")
    return label


def _edge_rel(edge_type: EdgeType | str) -> str:
    key = edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type)
    rel = _EDGE_RELS.get(key)
    if rel is None:
        raise ValueError(f"Unknown KB edge type: {key}")
    return rel


def _search_tokens(error_text: str) -> list[str]:
    """Pull distinctive error signatures out of a CI log for claim matching."""
    tokens = re.findall(
        r"(?:ModuleNotFoundError|ImportError|No module named ['\"]?\w+|error[:\s]+\w+|\w+Error)",
        error_text or "",
        flags=re.IGNORECASE,
    )
    if tokens:
        return tokens[:5]
    return re.findall(r"[A-Za-z_]{4,}", (error_text or "")[:800])[:8]


def _lucene_query(tokens: list[str]) -> str:
    quoted = []
    for token in tokens:
        escaped = _LUCENE_SPECIALS.sub(r"\\\1", token.strip())
        if escaped:
            quoted.append(f'"{escaped}"')
    return " OR ".join(quoted)


class KnowledgeStore:
    """Provenance graph operations over the Neo4j knowledge base."""

    def __init__(self, neo4j_service: Optional[Neo4jService] = None) -> None:
        self.neo4j = neo4j_service or get_neo4j_service()

    @property
    def enabled(self) -> bool:
        return self.neo4j is not None and self.neo4j.enabled

    async def _ready(self) -> bool:
        """Connect lazily so background tasks and scripts work without lifespan."""
        if self.neo4j is None:
            return False
        return await self.neo4j.ensure_connected()

    async def ensure_indexes(self) -> None:
        if self.neo4j is not None:
            await self.neo4j.ensure_schema()

    async def upsert_node(
        self,
        *,
        node_id: str,
        node_type: NodeType | str,
        label: str,
        properties: Optional[dict[str, Any]] = None,
        project_id: str = "",
    ) -> str:
        if not self.enabled:
            return node_id

        type_label = _node_label(node_type)
        type_value = node_type.value if isinstance(node_type, NodeType) else str(node_type)
        await self.neo4j.run(
            f"""
            MERGE (n:KBNode {{node_id: $node_id}})
            ON CREATE SET n.created_at = $now
            SET n:{type_label},
                n += $props,
                n.type = $type,
                n.label = $label,
                n.project_id = $project_id,
                n.updated_at = $now
            """,
            {
                "node_id": node_id,
                "props": encode_properties(properties or {}),
                "type": type_value,
                "label": label,
                "project_id": project_id,
                "now": _now(),
            },
        )
        return node_id

    async def add_edge(
        self,
        *,
        edge_type: EdgeType | str,
        from_id: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> str:
        edge_id = f"edge:{uuid.uuid4().hex[:16]}"
        if not self.enabled:
            return edge_id

        rel = _edge_rel(edge_type)
        type_value = edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type)
        await self.neo4j.run(
            f"""
            MATCH (a:KBNode {{node_id: $from_id}})
            MATCH (b:KBNode {{node_id: $to_id}})
            MERGE (a)-[r:{rel}]->(b)
            ON CREATE SET r.edge_id = $edge_id, r.created_at = $now
            SET r += $props, r.type = $type
            """,
            {
                "from_id": from_id,
                "to_id": to_id,
                "edge_id": edge_id,
                "props": encode_properties(properties or {}),
                "type": type_value,
                "now": _now(),
            },
        )
        return edge_id

    async def find_historical_fixes(
        self,
        *,
        project_id: str,
        error_text: str,
        limit: int = 3,
    ) -> list[HistoricalFixContext]:
        """
        Match Claim nodes against the current error, then traverse SUPPORTS to
        the newest non-superseded Artifact for each claim.
        """
        if not await self._ready():
            return []

        tokens = _search_tokens(error_text)
        if not tokens:
            return []

        params = {
            "index": CLAIM_FULLTEXT_INDEX,
            "query": _lucene_query(tokens),
            "project_id": project_id or "",
            "limit": limit,
        }

        records: list[dict[str, Any]] = []
        try:
            records = await self.neo4j.run(
                """
                CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
                WHERE node:Claim AND ($project_id = '' OR node.project_id = $project_id)
                WITH node AS claim, score
                ORDER BY score DESC
                LIMIT $limit
                OPTIONAL MATCH (claim)-[:SUPPORTS]->(art:Artifact)
                WHERE NOT EXISTS { (:Artifact)-[:SUPERSEDES]->(art) }
                WITH claim, score, art
                ORDER BY score DESC, coalesce(art.updated_at, '') DESC
                WITH claim, score, collect(art) AS artifacts
                RETURN claim, score, head(artifacts) AS artifact
                ORDER BY score DESC
                """,
                params,
                write=False,
            )
        except Exception as exc:
            print(f"[KB] Full-text claim search unavailable ({exc}); falling back to substring match")

        if not records:
            records = await self._fallback_claim_search(tokens, project_id, limit)

        results: list[HistoricalFixContext] = []
        for record in records:
            claim = decode_properties(record.get("claim") or {})
            artifact = decode_properties(record.get("artifact") or {})
            results.append(
                HistoricalFixContext(
                    claim_label=str(claim.get("label") or ""),
                    claim_id=str(claim.get("node_id") or ""),
                    artifact_summary=str(
                        artifact.get("label") or artifact.get("commit_message") or ""
                    ),
                    artifact_patches=list(artifact.get("file_patches") or []),
                    commit_message=str(artifact.get("commit_message") or ""),
                    pipeline_id=str(artifact.get("pipeline_id") or ""),
                    score_hint=", ".join(tokens[:3]),
                )
            )
        return results

    async def _fallback_claim_search(
        self, tokens: list[str], project_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Substring search used when the full-text index is missing or empty."""
        try:
            return await self.neo4j.run(
                """
                MATCH (claim:Claim)
                WHERE ($project_id = '' OR claim.project_id = $project_id)
                  AND any(token IN $tokens WHERE
                        toLower(coalesce(claim.label, '')) CONTAINS toLower(token)
                     OR toLower(coalesce(claim.root_cause, '')) CONTAINS toLower(token))
                WITH claim
                ORDER BY coalesce(claim.updated_at, '') DESC
                LIMIT $limit
                OPTIONAL MATCH (claim)-[:SUPPORTS]->(art:Artifact)
                WHERE NOT EXISTS { (:Artifact)-[:SUPERSEDES]->(art) }
                WITH claim, art
                ORDER BY coalesce(art.updated_at, '') DESC
                WITH claim, collect(art) AS artifacts
                RETURN claim, 0.0 AS score, head(artifacts) AS artifact
                """,
                {"tokens": tokens, "project_id": project_id or "", "limit": limit},
                write=False,
            )
        except Exception as exc:
            print(f"[KB] Claim search failed: {exc}")
            return []

    async def record_successful_fix(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        root_cause: str,
        commit_message: str,
        file_patches: list[dict[str, str]],
        architecture_plan: Optional[dict[str, Any]] = None,
        logs_excerpt: str = "",
        run_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, str]:
        """
        Additive write after human approval/merge.
        Links Run → Claim → Artifact and supersedes prior artifacts for the claim.
        """
        claim_id = _claim_id(project_id, root_cause)
        source_id = f"source:{project_id}:{pipeline_id}"
        run_id = f"run:{project_id}:{pipeline_id}:{uuid.uuid4().hex[:8]}"
        artifact_id = f"artifact:{project_id}:{pipeline_id}:{uuid.uuid4().hex[:8]}"

        ids = {
            "claim_id": claim_id,
            "artifact_id": artifact_id,
            "run_id": run_id,
            "source_id": source_id,
        }
        if not await self._ready():
            print("[KB] Neo4j disabled - skipping knowledge write")
            return ids

        # Capture prior artifacts before the new one is linked to the claim.
        previous = await self.neo4j.run(
            """
            MATCH (claim:Claim {node_id: $claim_id})-[:SUPPORTS]->(art:Artifact)
            WHERE NOT EXISTS { (:Artifact)-[:SUPERSEDES]->(art) }
            RETURN art.node_id AS node_id
            """,
            {"claim_id": claim_id},
            write=False,
        )

        await self.upsert_node(
            node_id=source_id,
            node_type=NodeType.SOURCE,
            label=f"pipeline {pipeline_id}",
            properties={"pipeline_id": pipeline_id, "logs_excerpt": (logs_excerpt or "")[:1500]},
            project_id=project_id,
        )
        await self.upsert_node(
            node_id=claim_id,
            node_type=NodeType.CLAIM,
            label=root_cause[:200],
            properties={
                "root_cause": root_cause,
                "architecture_plan": architecture_plan or {},
            },
            project_id=project_id,
        )
        await self.upsert_node(
            node_id=run_id,
            node_type=NodeType.RUN,
            label=f"run {pipeline_id}",
            properties=run_metadata or {"pipeline_id": pipeline_id},
            project_id=project_id,
        )
        await self.upsert_node(
            node_id=artifact_id,
            node_type=NodeType.ARTIFACT,
            label=commit_message[:200] or f"fix for {pipeline_id}",
            properties={
                "commit_message": commit_message,
                "file_patches": file_patches,
                "pipeline_id": pipeline_id,
                "root_cause": root_cause,
            },
            project_id=project_id,
        )

        for patch in file_patches:
            path = patch.get("file_path") or ""
            if not path:
                continue
            entity_id = f"entity:file:{_slug(path, 64)}"
            await self.upsert_node(
                node_id=entity_id,
                node_type=NodeType.ENTITY,
                label=path,
                properties={"kind": "file", "path": path},
                project_id=project_id,
            )
            await self.add_edge(
                edge_type=EdgeType.MENTIONS,
                from_id=artifact_id,
                to_id=entity_id,
            )

        await self.add_edge(edge_type=EdgeType.DERIVED_FROM, from_id=artifact_id, to_id=claim_id)
        await self.add_edge(edge_type=EdgeType.SUPPORTS, from_id=claim_id, to_id=artifact_id)
        await self.add_edge(edge_type=EdgeType.DERIVED_FROM, from_id=claim_id, to_id=source_id)
        await self.add_edge(edge_type=EdgeType.DERIVED_FROM, from_id=run_id, to_id=source_id)
        await self.add_edge(edge_type=EdgeType.SUPPORTS, from_id=run_id, to_id=artifact_id)

        for row in previous:
            old_artifact = row.get("node_id")
            if old_artifact and old_artifact != artifact_id:
                await self.add_edge(
                    edge_type=EdgeType.SUPERSEDES,
                    from_id=artifact_id,
                    to_id=old_artifact,
                    properties={"reason": "newer_approved_fix"},
                )

        return ids


def get_knowledge_store(neo4j_service: Optional[Neo4jService] = None) -> KnowledgeStore:
    return KnowledgeStore(neo4j_service or get_neo4j_service())
