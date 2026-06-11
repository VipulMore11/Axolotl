from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Event(BaseModel):
    timestamp: datetime
    session_id: str
    user_id: Optional[str] = None
    event_type: str
    message: str
    metadata: Optional[dict] = None