"""
Activity API Routes
Provides agent activity events and lifetime metrics from MongoDB.
"""

from fastapi import APIRouter, Depends

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/events")
async def get_activity_events(
    user: UserResponse = Depends(get_current_user),
    limit: int = 50,
    event_type: str = None,
):
    """
    List agent activity events, newest first.
    Maps orchestration events to the frontend ActivityEvent format.
    """
    mongo = get_mongo_service()
    raw_events = await mongo.get_events(
        user_id=user.id,
        limit=limit,
        event_type=event_type,
    )

    events = []
    for ev in raw_events:
        metadata = ev.get("metadata") or {}
        ts = ev.get("timestamp")
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else ""

        events.append({
            "id": str(ev.get("_id", "")),
            "time": ts_str,
            "date": _format_date(ts),
            "type": _map_event_type(ev.get("event_type", "")),
            "pipeline": metadata.get("pipeline_id", ""),
            "project": metadata.get("project_id", ""),
            "summary": ev.get("message", ""),
            "detail": ev.get("message", ""),
            "session_id": ev.get("session_id", ""),
            "model": metadata.get("model"),
            "confidence": metadata.get("confidence"),
        })

    return {"events": events, "total": len(events)}


@router.get("/metrics")
async def get_activity_metrics(
    user: UserResponse = Depends(get_current_user),
):
    """Aggregate lifetime agent metrics."""
    mongo = get_mongo_service()
    metrics = await mongo.get_agent_metrics(user_id=user.id)
    return {"metrics": metrics}


def _map_event_type(event_type: str) -> str:
    """Map backend event types to frontend activity event types."""
    mapping = {
        "pipeline_failed": "detection",
        "fetching_logs": "detection",
        "analyzing": "analysis",
        "generating_fix": "fix",
        "creating_branch": "fix",
        "committing": "fix",
        "creating_mr": "merge-request",
        "waiting_approval": "approval",
        "fix_succeeded": "merged",
        "fix_failed": "rejected",
    }
    return mapping.get(event_type, "detection")


def _format_date(ts) -> str:
    """Format a timestamp to a date label (Today / Yesterday / date)."""
    if not ts:
        return ""
    from datetime import datetime, UTC
    try:
        now = datetime.now(UTC)
        if hasattr(ts, "date"):
            d = ts.date()
        else:
            return ""
        if d == now.date():
            return "Today"
        from datetime import timedelta
        if d == (now - timedelta(days=1)).date():
            return "Yesterday"
        return d.strftime("%b %d")
    except Exception:
        return ""
