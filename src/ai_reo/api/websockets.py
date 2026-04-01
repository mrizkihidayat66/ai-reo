"""Real-time bi-directional WebSocket management."""

import json
from typing import Any, Dict, List

from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSockets segmented by Session IDs."""

    def __init__(self) -> None:
        # Dictionary bridging a session_id to an active list of WebSocket descriptors
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a new connection and store it contextually."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        
        # Acknowledge connection natively to UI
        await self.broadcast_to_session(session_id, {"type": "system", "message": "Connected to AI-REO WebSocket backend."})

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Purge dropped sockets."""
        if session_id in self.active_connections:
            try:
                self.active_connections[session_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast_to_session(self, session_id: str, message: Dict[str, Any]) -> None:
        """Broadcast an arbitrary JSON payload globally to all viewing clients of an analysis session."""
        if session_id not in self.active_connections:
            return

        data = json.dumps(message, default=str)
        
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(data)
            except Exception:
                # Silently handle detached connections
                pass

# Global orchestrator singleton
manager = ConnectionManager()
