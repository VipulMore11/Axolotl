"""
Dashboard API Routes
Provides aggregated dashboard data: summary stats and active pipeline sessions.
"""

from fastapi import APIRouter, Depends

from auth.schemas import UserResponse
from core.auth import get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_dashboard_summary(user: UserResponse = Depends(get_current_user)):
    """
    Aggregated dashboard statistics:
    - Number of watched projects
    - Agent metrics (failures, fixes, success rate)
    """
    mongo = get_mongo_service()
    projects = await mongo.get_projects_for_user(user.id)
    metrics = await mongo.get_agent_metrics(user_id=user.id)

    return {
        "projects_count": len(projects),
        "metrics": metrics,
    }


@router.get("/active-session")
async def get_active_session(user: UserResponse = Depends(get_current_user)):
    """
    Return the most recent active pipeline fix session (if any).
    Used by the Overview page to display real-time agent workflow.
    """
    mongo = get_mongo_service()

    # Find the most recent pipeline_failed event that doesn't have a
    # corresponding fix_succeeded or fix_failed event yet.
    recent_events = await mongo.get_events(user_id=user.id, limit=100)

    # Group events by session_id
    sessions: dict = {}
    for ev in recent_events:
        sid = ev.get("session_id", "unknown")
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(ev)

    # Find a session that has pipeline_failed but no terminal event
    active_session = None
    for sid, events in sessions.items():
        event_types = {e.get("event_type") for e in events}
        has_start = "pipeline_failed" in event_types
        has_terminal = "fix_succeeded" in event_types or "fix_failed" in event_types or "waiting_approval" in event_types

        if has_start:
            # Convert ObjectId to string for JSON serialization
            serialized_events = []
            for e in events:
                e_copy = {**e}
                if "_id" in e_copy:
                    e_copy["_id"] = str(e_copy["_id"])
                if "timestamp" in e_copy:
                    e_copy["timestamp"] = e_copy["timestamp"].isoformat() if hasattr(e_copy["timestamp"], "isoformat") else str(e_copy["timestamp"])
                serialized_events.append(e_copy)

            active_session = {
                "session_id": sid,
                "events": serialized_events,
                "is_complete": has_terminal,
            }
            if not has_terminal:
                break  # Prefer an incomplete (still active) session

    return {"active_session": active_session}
