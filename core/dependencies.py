"""
Core dependencies — singleton service instances for the Axolotl application.
All shared services are instantiated here and imported by routes/orchestrator.
"""

from ws.connection_manager import ConnectionManager
from observability.local_observability import LocalObservability
from ws.event_publisher import EventPublisher

# ─── WebSocket & Observability (Person 4) ───────────────────────────
connection_manager = ConnectionManager()

observability = LocalObservability()

event_publisher = EventPublisher(
    connection_manager=connection_manager,
    observability=observability,
)

# ─── MongoDB (Person 2) ────────────────────────────────────────────
from db.mongo_service import get_mongo_service  # noqa: E402

mongo_service = get_mongo_service()

# ─── Orchestrator (lazy init to avoid circular imports) ─────────────
_orchestrator = None


def get_orchestrator():
    """
    Lazily construct the PipelineOrchestrator with all dependencies wired.
    Called by webhook routes when a pipeline failure arrives.
    """
    global _orchestrator

    if _orchestrator is None:
        from orchestrator.pipeline_orchestrator import PipelineOrchestrator

        _orchestrator = PipelineOrchestrator(
            event_publisher=event_publisher,
            mongo_service=mongo_service,
        )

    return _orchestrator