from abc import ABC, abstractmethod

from schemas.fix import FixProposal


class BaseAgent(ABC):
    """Base interface for all CI-fix agents."""

    @abstractmethod
    async def analyze(self, logs: str) -> FixProposal:
        """Inspect pipeline logs and return a structured fix proposal."""
        raise NotImplementedError
