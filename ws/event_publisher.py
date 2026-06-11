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

        await self.connection_manager.send_message(
            session_id=event.session_id,
            payload={
                "timestamp": (
                    event.timestamp.isoformat()
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
        )