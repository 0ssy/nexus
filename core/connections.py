import json
from fastapi import WebSocket
from typing import Dict

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.room_subscriptions: Dict[str, set] = {}

    async def connect(self, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[agent_id] = websocket

    def disconnect(self, agent_id: str):
        self.connections.pop(agent_id, None)
        for room_id in list(self.room_subscriptions.keys()):
            self.room_subscriptions[room_id].discard(agent_id)

    def subscribe_to_room(self, agent_id: str, room_id: str):
        if room_id not in self.room_subscriptions:
            self.room_subscriptions[room_id] = set()
        self.room_subscriptions[room_id].add(agent_id)

    def unsubscribe_from_room(self, agent_id: str, room_id: str):
        if room_id in self.room_subscriptions:
            self.room_subscriptions[room_id].discard(agent_id)

    async def send_to_agent(self, agent_id: str, event: str, data: dict):
        ws = self.connections.get(agent_id)
        if ws:
            try:
                await ws.send_text(json.dumps({"event": event, "data": data}))
            except Exception:
                self.disconnect(agent_id)

    def is_connected(self, agent_id: str) -> bool:
        return agent_id in self.connections

    async def broadcast_to_room(self, room_id: str, event: str, data: dict, exclude: str = None):
        subscribers = self.room_subscriptions.get(room_id, set())
        for agent_id in list(subscribers):
            if exclude and agent_id == exclude:
                continue
            await self.send_to_agent(agent_id, event, data)
# Global instance
manager = ConnectionManager()
