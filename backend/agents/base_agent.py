from abc import ABC, abstractmethod

from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure


class BaseAgent(ABC):
    """Abstract contract for all CI-fix agents."""

    @abstractmethod
    async def analyze(self, failure: PipelineFailure) -> FixProposal:
        """Inspect a pipeline failure and return a structured fix proposal."""
        raise NotImplementedError
