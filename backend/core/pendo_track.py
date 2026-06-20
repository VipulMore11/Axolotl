"""
Pendo server-side Track Event utility.
Sends track events to the Pendo data API via HTTP POST.
"""

import time
import httpx

PENDO_TRACK_URL = "https://data.pendo.io/data/track"
PENDO_INTEGRATION_KEY = "35bc5a48-02e1-49bc-963b-dff11fd23021"


async def pendo_track(
    event: str,
    visitor_id: str | None = None,
    account_id: str | None = None,
    properties: dict | None = None,
) -> None:
    """
    Send a track event to Pendo's server-side API.

    Args:
        event: Descriptive event name
        visitor_id: Unique user identifier (falls back to "system")
        account_id: Unique account identifier (falls back to "system")
        properties: Optional metadata dict
    """
    payload = {
        "type": "track",
        "event": event,
        "visitorId": visitor_id or "system",
        "accountId": account_id or "system",
        "timestamp": int(time.time() * 1000),
    }
    if properties:
        payload["properties"] = properties

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                PENDO_TRACK_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-pendo-integration-key": PENDO_INTEGRATION_KEY,
                },
                timeout=5.0,
            )
    except Exception as e:
        print(f"[Pendo] Failed to send track event '{event}': {e}")
