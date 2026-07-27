"""
Neo4j graph database service for the Axolotl Knowledge Base.

Backs the Entity / Claim / Source / Artifact / Run provenance graph used for
cross-session grounding during `requirements_analysis` and for post-HITL
knowledge extraction after a fix is approved or merged.

Configuration (matches the credentials file Neo4j Aura hands out):
    NEO4J_URI       neo4j+s://<instance>.databases.neo4j.io
    NEO4J_USERNAME  neo4j
    NEO4J_PASSWORD  <instance password / API key>
    NEO4J_DATABASE  neo4j
    NEO4J_ENABLED   set to false to hard-disable the KB

When credentials are absent the service stays disabled and every operation is a
no-op, so the CI-fix pipeline keeps running without a graph database.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

try:  # Driver is optional so the backend still boots without the KB extra
    from neo4j import AsyncDriver, AsyncGraphDatabase, RoutingControl
    from neo4j.exceptions import Neo4jError

    _DRIVER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in trimmed installs
    AsyncDriver = Any  # type: ignore[assignment,misc]
    AsyncGraphDatabase = None  # type: ignore[assignment]
    RoutingControl = None  # type: ignore[assignment]
    Neo4jError = Exception  # type: ignore[assignment,misc]

    _DRIVER_AVAILABLE = False


CLAIM_FULLTEXT_INDEX = "kb_claim_fulltext"

# Neo4j properties must be primitives or arrays of primitives. Anything nested
# (architecture_plan, file_patches) is JSON-encoded and listed in _json_keys.
_JSON_KEYS_PROP = "_json_keys"


def _is_primitive(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(isinstance(item, (str, int, float, bool)) for item in value)
    return False


def encode_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Flatten a property dict into Neo4j-storable values."""
    encoded: dict[str, Any] = {}
    json_keys: list[str] = []
    for key, value in (properties or {}).items():
        if value is None:
            continue
        if _is_primitive(value):
            encoded[key] = value
        else:
            encoded[key] = json.dumps(value, default=str)
            json_keys.append(key)
    encoded[_JSON_KEYS_PROP] = json_keys
    return encoded


def decode_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Inverse of `encode_properties`."""
    decoded = dict(properties or {})
    json_keys = decoded.pop(_JSON_KEYS_PROP, []) or []
    for key in json_keys:
        raw = decoded.get(key)
        if isinstance(raw, str):
            try:
                decoded[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return decoded


class Neo4jService:
    """Thin async wrapper around the Neo4j driver with graceful degradation."""

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self.uri = uri or os.getenv("NEO4J_URI") or os.getenv("NEO4J_URL", "")
        self.username = (
            username or os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER") or "neo4j"
        )
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        self.driver: Optional[AsyncDriver] = None
        self._schema_ready = False

    @property
    def configured(self) -> bool:
        if os.getenv("NEO4J_ENABLED", "true").strip().lower() in {"false", "0", "no"}:
            return False
        return bool(_DRIVER_AVAILABLE and self.uri and self.password)

    @property
    def enabled(self) -> bool:
        return self.driver is not None

    async def connect(self) -> bool:
        """Open the driver and provision schema. Returns True when usable."""
        if self.driver is not None:
            return True
        if not self.configured:
            if not _DRIVER_AVAILABLE:
                print("[Neo4j] Driver not installed - knowledge base disabled")
            else:
                print("[Neo4j] NEO4J_URI/NEO4J_PASSWORD not set - knowledge base disabled")
            return False

        try:
            self.driver = AsyncGraphDatabase.driver(
                self.uri, auth=(self.username, self.password)
            )
            await self.driver.verify_connectivity()
        except Exception as exc:
            print(f"[Neo4j] Connection failed ({exc}) - knowledge base disabled")
            await self._close_driver()
            return False

        print(f"[Neo4j] Connected to {self.uri}, database: {self.database}")
        await self.ensure_schema()
        return True

    async def ensure_connected(self) -> bool:
        """Connect on demand for callers outside the FastAPI lifespan."""
        if self.enabled:
            return True
        return await self.connect()

    async def disconnect(self) -> None:
        if self.driver is not None:
            await self._close_driver()
            print("[Neo4j] Disconnected")

    async def _close_driver(self) -> None:
        driver, self.driver = self.driver, None
        self._schema_ready = False
        if driver is not None:
            try:
                await driver.close()
            except Exception:
                pass

    async def ensure_schema(self) -> None:
        """Create uniqueness constraints and the Claim full-text index."""
        if not self.enabled or self._schema_ready:
            return

        statements = [
            "CREATE CONSTRAINT kb_node_id IF NOT EXISTS "
            "FOR (n:KBNode) REQUIRE n.node_id IS UNIQUE",
            "CREATE INDEX kb_node_type_project IF NOT EXISTS "
            "FOR (n:KBNode) ON (n.type, n.project_id)",
            f"CREATE FULLTEXT INDEX {CLAIM_FULLTEXT_INDEX} IF NOT EXISTS "
            "FOR (n:Claim) ON EACH [n.label, n.root_cause]",
        ]
        for statement in statements:
            try:
                await self.run(statement)
            except Exception as exc:
                print(f"[Neo4j] Schema warning: {exc}")

        self._schema_ready = True
        print("[Neo4j] Knowledge base schema ready (KBNode constraint + Claim full-text index)")

    async def run(
        self,
        query: str,
        parameters: Optional[dict[str, Any]] = None,
        *,
        write: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute Cypher and return records as plain dicts. Empty when disabled."""
        if not self.enabled:
            return []
        result = await self.driver.execute_query(
            query,
            parameters or {},
            database_=self.database,
            routing_=RoutingControl.WRITE if write else RoutingControl.READ,
        )
        return [record.data() for record in result.records]


_neo4j_service: Optional[Neo4jService] = None


def get_neo4j_service() -> Neo4jService:
    """Get or create the Neo4j service singleton."""
    global _neo4j_service

    if _neo4j_service is None:
        _neo4j_service = Neo4jService()

    return _neo4j_service
