from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from websocket.connection_manager import (
    ConnectionManager
)

router = APIRouter()

manager = ConnectionManager()


@router.websocket(
    "/ws/{session_id}"
)
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str
):

    await manager.connect(
        session_id,
        websocket
    )

    try:

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect(
            session_id,
            websocket
        )