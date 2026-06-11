# debug_route.py

import asyncio
from datetime import datetime, UTC

from fastapi import APIRouter

from schemas.events import Event

from core.dependencies import (
    event_publisher
)

router = APIRouter()


@router.get("/debug/spam")
async def spam_events():
    """
    Test Endpoint

    1. Connect Postman:
       ws://localhost:8000/ws/123

    2. Hit:
       http://localhost:8000/debug/spam

    3. Verify 100 messages are received
    """

    for i in range(100):

        event = Event(
            timestamp=datetime.now(UTC),
            session_id="123",
            event_type="TEST_EVENT",
            message=f"Message {i}",
            metadata={
                "count": i
            }
        )

        await event_publisher.publish(event)

        await asyncio.sleep(0.1)

    return {
        "status": "completed",
        "messages_sent": 100
    }