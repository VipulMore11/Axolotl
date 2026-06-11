from pydantic import BaseModel


class PipelineContext(BaseModel):
    project_id: str
    pipeline_id: str
    session_id: str