from dataclasses import dataclass


@dataclass
class Event:
    """Simple event payload for pipeline and agent activity logs."""

    timestamp: str
    message: str
