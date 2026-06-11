from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from core.dependencies import (
    connection_manager
)

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str
):

    print(
        f"[WS CONNECTED] {session_id}"
    )

    await connection_manager.connect(
        session_id,
        websocket
    )

    try:

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:

        print(
            f"[WS DISCONNECTED] {session_id}"
        )

        connection_manager.disconnect(
            session_id,
            websocket
        )