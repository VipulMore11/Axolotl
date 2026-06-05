from schemas.events import Event
from websocket.connection_manager import (
    ConnectionManager
)


class EventPublisher:
    def __init__(
        self,
        connection_manager: ConnectionManager
    ):
        self.connection_manager = (
            connection_manager
        )

    async def publish(
        self,
        event: Event
    ):
        await self.connection_manager.send_message(
            session_id=event.session_id,
            message={
                "timestamp": str(
                    event.timestamp
                ),
                "event_type": (
                    event.event_type
                ),
                "message": event.message,
                "metadata": (
                    event.metadata
                )
            }
        )