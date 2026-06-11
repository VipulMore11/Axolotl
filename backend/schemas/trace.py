from pydantic import BaseModel
from typing import Optional


class AgentTrace(BaseModel):
    session_id: str
    input_data: str
    reasoning: str
    output_data: str
    metadata: Optional[dict] = None