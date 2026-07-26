from enum import Enum


class EventType(Enum):
    """Enumerates pipeline and fix workflow events for orchestration."""

    PIPELINE_FAILED = "pipeline_failed"
    FETCHING_LOGS = "fetching_logs"

    # Eight-stage LangGraph CI fix pipeline
    WORKSPACE_SETUP = "workspace_setup"
    REQUIREMENTS_ANALYSIS = "requirements_analysis"
    TECHNICAL_ARCHITECTURE = "technical_architecture"
    TASK_BREAKDOWN = "task_breakdown"
    CODE_IMPLEMENTATION = "code_implementation"
    TESTING_VALIDATION = "testing_validation"
    CODE_REVIEW = "code_review"
    GIT_OPERATIONS = "git_operations"

    # Legacy aliases kept for backward-compatible log consumers
    ANALYZING = "analyzing"
    GENERATING_FIX = "generating_fix"
    VALIDATING = "validating"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    CREATING_BRANCH = "creating_branch"
    COMMITTING = "committing"
    CREATING_MR = "creating_mr"

    WAITING_APPROVAL = "waiting_approval"
    FIX_SUCCEEDED = "fix_succeeded"
    FIX_FAILED = "fix_failed"
