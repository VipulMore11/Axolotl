from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Event(BaseModel):
    timestamp: datetime
    session_id: str
    event_type: str
    message: str
    metadata: Optional[dict] = None