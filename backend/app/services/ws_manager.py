from fastapi import WebSocket
from typing import Dict, List
import json
import logging

logger = logging.getLogger("app.websocket")

class WebSocketManager:
    def __init__(self):
        # Maps session_id (str) -> list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket connected for session: {session_id}. Total active: {len(self.active_connections[session_id])}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
                logger.info(f"WebSocket disconnected for session: {session_id}.")
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast_to_session(self, session_id: str, message: dict):
        from fastapi.encoders import jsonable_encoder
        if session_id in self.active_connections:
            stale_connections = []
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(jsonable_encoder(message))
                except Exception as e:
                    logger.error(f"Failed to send websocket message: {e}")
                    stale_connections.append(connection)
            
            # Clean up broken connections
            for stale in stale_connections:
                self.disconnect(stale, session_id)

ws_manager = WebSocketManager()
