from fastapi import WebSocket
from typing import Dict, List


class ConnectionManager:
    def __init__(self):
        """
        session_id -> list of websockets
        """
        self.active_connections: Dict[
            str,
            List[WebSocket]
        ] = {}

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket
    ):
        await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = []

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
        message: dict
    ):
        if session_id not in self.active_connections:
            return

        for connection in self.active_connections[
            session_id
        ]:
            await connection.send_json(message)