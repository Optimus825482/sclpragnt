"""WebSocket client lifecycle and fan-out primitives."""

import asyncio


class ConnectionManager:
    def __init__(self):
        self.active_connections = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        async with self._lock:
            if websocket not in self.active_connections:
                self.active_connections.append(websocket)

    async def disconnect(self, websocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        connections = list(self.active_connections)

        async def send(websocket):
            try:
                # One stalled browser cannot block the other clients.
                await asyncio.wait_for(websocket.send_json(message), timeout=0.75)
            except Exception:
                await self.disconnect(websocket)

        # Fan out concurrently: total latency is bounded by one client timeout,
        # not timeout multiplied by the number of connected browsers.
        if connections:
            await asyncio.gather(*(send(websocket) for websocket in connections))


ws_manager = ConnectionManager()
