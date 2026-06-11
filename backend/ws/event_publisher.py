from schemas.events import Event
from observability.base_observability import (
    BaseObservability
)
from ws.connection_manager import (
    ConnectionManager
)


class EventPublisher:
    def __init__(
        self,
        connection_manager: ConnectionManager,
        observability: BaseObservability
    ):
        self.connection_manager = (
            connection_manager
        )

        self.observability = (
            observability
        )

    async def publish(
        self,
        event: Event
    ):
        await self.observability.log_event(
            event
        )

        payload = {
            "timestamp": (
                event.timestamp.isoformat()
            ),
            "session_id": (
                event.session_id
            ),
            "event_type": (
                event.event_type
            ),
            "message": (
                event.message
            ),
            "metadata": (
                event.metadata
            )
        }

        # Send to the pipeline-specific session
        await self.connection_manager.send_message(
            session_id=event.session_id,
            payload=payload
        )

        # Also broadcast to the global 'dashboard' channel
        # so the Overview page always receives events
        if event.session_id != "dashboard":
            await self.connection_manager.send_message(
                session_id="dashboard",
                payload=payload
            )