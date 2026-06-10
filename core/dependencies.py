from ws.connection_manager import (
    ConnectionManager
)

from observability.local_observability import (
    LocalObservability
)

from ws.event_publisher import (
    EventPublisher
)

connection_manager = ConnectionManager()

observability = LocalObservability()

event_publisher = EventPublisher(
    connection_manager=connection_manager,
    observability=observability
)