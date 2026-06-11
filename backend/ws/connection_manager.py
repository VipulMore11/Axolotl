from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        """
        session_id -> list[WebSocket]
        """
        self.active_connections = defaultdict(list)

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket
    ):
        await websocket.accept()

        self.active_connections[
            session_id
        ].append(websocket)

    def disconnect(
        self,
        session_id: str,
        websocket: WebSocket
    ):
        if session_id not in self.active_connections:
            return

        if websocket in self.active_connections[
            session_id
        ]:
            self.active_connections[
                session_id
            ].remove(websocket)

    async def send_message(
        self,
        session_id: str,
        payload: dict
    ):
        if session_id not in self.active_connections:
            return

        for websocket in self.active_connections[
            session_id
        ]:
            await websocket.send_json(payload)