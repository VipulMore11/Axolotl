from abc import ABC, abstractmethod
from schemas.events import Event
from schemas.trace import AgentTrace


class BaseObservability(ABC):

    @abstractmethod
    async def log_event(
        self,
        event: Event
    ):
        pass

    @abstractmethod
    async def create_trace(
        self,
        trace: AgentTrace
    ):
        pass