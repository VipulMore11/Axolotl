"""LangGraph state and artifact contracts for the eight-stage CI fix pipeline."""

from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ArchitecturePlan(TypedDict):
    """Architect Agent output — low-blast-radius fix strategy."""

    strategy_type: str  # deps | lint | format | code_patch
    affected_files: list[str]
    proposed_solution: str


class CritiqueResult(TypedDict):
    """Evaluator Agent critique — must cite line numbers when rejecting."""

    satisfactory: bool
    issues: list[str]
    revision_instructions: list[str]


def empty_architecture_plan() -> ArchitecturePlan:
    return {
        "strategy_type": "",
        "affected_files": [],
        "proposed_solution": "",
    }


class CIFixState(TypedDict):
    """Explicit workspace + artifact state for the CI fix graph."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    project_id: str
    pipeline_id: str
    branch: str
    logs: str
    root_cause: str
    architecture_plan: ArchitecturePlan
    task_breakdown: list[str]
    file_path: str
    updated_content: str
    commit_message: str
    validation_output: str
    validation_passed: bool
    validation_failures: list[str]
    review_history: list[CritiqueResult]
    review_approved: bool
    attempts: int
    current_stage: str
