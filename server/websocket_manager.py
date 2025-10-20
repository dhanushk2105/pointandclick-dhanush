"""WebSocket connection management."""

import asyncio
import json
from typing import Dict
from fastapi import WebSocket
from .utils import log_detail


class ConnectionManager:
    """Manages WebSocket connections and message routing."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.pending_responses: Dict[str, asyncio.Future] = {}
    
    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        log_detail("✅", f"WebSocket connected", f"Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        log_detail("❌", f"WebSocket disconnected", f"Remaining: {len(self.active_connections)}")
    
    async def send_action(self, websocket: WebSocket, action_id: str, action: str, payload: dict):
        """Send an action to the extension via WebSocket."""
        message = {"id": action_id, "action": action, "payload": payload}
        await websocket.send_json(message)
        log_detail("📤", f"Sent action: {action}", f"ID: {action_id}\nPayload: {json.dumps(payload, indent=2)}")
    
    def create_response_future(self, action_id: str) -> asyncio.Future:
        """Create a future for waiting on an action response."""
        future = asyncio.Future()
        self.pending_responses[action_id] = future
        log_detail("⏳", f"Waiting for response", f"Action ID: {action_id}")
        return future
    
    def resolve_response(self, action_id: str, response: dict):
        """Resolve a pending response future."""
        if action_id in self.pending_responses:
            if not self.pending_responses[action_id].done():
                self.pending_responses[action_id].set_result(response)
                log_detail("📥", f"Received response", f"ID: {action_id}\nStatus: {response.get('status')}")
            del self.pending_responses[action_id]
    
    def has_connections(self) -> bool:
        """Check if there are any active connections."""
        return len(self.active_connections) > 0
    
    def get_first_connection(self) -> WebSocket:
        """Get the first active connection (for single-client scenarios)."""
        if not self.active_connections:
            raise RuntimeError("No active WebSocket connections")
        return self.active_connections[0]
    
    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Connection might be broken, will be cleaned up elsewhere
                pass
    
    def cleanup_stale_futures(self):
        """Clean up any futures that are done or cancelled."""
        stale = [
            action_id for action_id, future in self.pending_responses.items()
            if future.done() or future.cancelled()
        ]
        for action_id in stale:
            del self.pending_responses[action_id]


# Global connection manager instance
manager = ConnectionManager()