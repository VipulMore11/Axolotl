from enum import Enum


class EventType(Enum):
    """Enumerates pipeline and fix workflow events for orchestration."""

    PIPELINE_FAILED = "pipeline_failed"
    FETCHING_LOGS = "fetching_logs"
    ANALYZING = "analyzing"
    GENERATING_FIX = "generating_fix"
    CREATING_BRANCH = "creating_branch"
    COMMITTING = "committing"
    CREATING_MR = "creating_mr"
    WAITING_APPROVAL = "waiting_approval"
    FIX_SUCCEEDED = "fix_succeeded"
    FIX_FAILED = "fix_failed"
