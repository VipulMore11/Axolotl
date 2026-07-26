"""Shared exceptions for CI fix agents."""


class CIFixAgentError(RuntimeError):
    """Raised when CI fix analysis fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
