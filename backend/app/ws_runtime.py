"""WebSocket client lifecycle and fan-out primitives."""

import asyncio


class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for websocket in list(self.active_connections):
            try:
                # One stalled browser cannot block the other clients.
                await asyncio.wait_for(websocket.send_json(message), timeout=0.75)
            except Exception:
                self.disconnect(websocket)


ws_manager = ConnectionManager()
