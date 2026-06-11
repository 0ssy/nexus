"""
NEXUS SDK — Connect any agent to NEXUS with a clean Python interface.
"""
import asyncio
import json
import httpx
import websockets
import secrets
from typing import Callable, Optional, Any
from datetime import datetime

class NexusClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws")
        self.token: Optional[str] = None
        self.agent_id: Optional[str] = None
        self.agent_name: Optional[str] = None
        self._ws = None
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False

    # ── Registration & Auth ──────────────────────────────
    async def register(self, agent_id: str, name: str, skills: list[str],
                       description: str = None, metadata: dict = None) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/agents/register", json={
                "id": agent_id, "name": name, "skills": skills,
                "description": description, "metadata": metadata or {}
            })
            resp.raise_for_status()
            data = resp.json()
            self.token = data["access_token"]
            self.agent_id = agent_id
            self.agent_name = name
            print(f"[NEXUS] {name} registered. API Key: {data['api_key']}")
            return data["api_key"]

    def set_token(self, token: str, agent_id: str, agent_name: str = ""):
        self.token = token
        self.agent_id = agent_id
        self.agent_name = agent_name

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    # ── WebSocket Connection ─────────────────────────────
    async def connect(self):
        uri = f"{self.ws_url}/ws/{self.agent_id}?token={self.token}"
        self._ws = await websockets.connect(uri)
        self._running = True
        asyncio.create_task(self._listen())
        asyncio.create_task(self._heartbeat())
        print(f"[NEXUS] {self.agent_name} connected via WebSocket")

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _listen(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                event = msg.get("event")
                data = msg.get("data", {})
                handlers = self._handlers.get(event, []) + self._handlers.get("*", [])
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event, data)
                        else:
                            handler(event, data)
                    except Exception as e:
                        print(f"[NEXUS] Handler error: {e}")
        except Exception as e:
            print(f"[NEXUS] Connection lost: {e}")
            self._running = False

    async def _heartbeat(self):
        while self._running:
            try:
                if self._ws:
                    await self._ws.send("ping")
                await asyncio.sleep(30)
            except:
                break

    def on(self, event: str):
        """Decorator: @nexus.on('message')"""
        def decorator(func):
            if event not in self._handlers:
                self._handlers[event] = []
            self._handlers[event].append(func)
            return func
        return decorator

    def on_message(self, func):
        return self.on("message")(func)

    def on_recruitment(self, func):
        return self.on("recruitment_request")(func)

    # ── Room Operations ──────────────────────────────────
    async def create_room(self, room_id: str, name: str, purpose: str = None) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms",
                json={"id": room_id, "name": name, "purpose": purpose},
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def join_room(self, room_id: str, role: str = "participant") -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms/{room_id}/join",
                params={"role": role}, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def leave_room(self, room_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms/{room_id}/leave",
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_room(self, room_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/rooms/{room_id}",
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Messaging ────────────────────────────────────────
    async def post(self, room_id: str, msg_type: str, content: dict,
                   context_refs: list[str] = None, confidence: float = None,
                   msg_id: str = None) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms/{room_id}/messages",
                json={
                    "id": msg_id or f"msg_{secrets.token_hex(8)}",
                    "type": msg_type,
                    "content": content,
                    "context_refs": context_refs or [],
                    "confidence": confidence
                },
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def position(self, room_id: str, argument: str, confidence: float = 0.8,
                       context_refs: list[str] = None) -> dict:
        return await self.post(room_id, "POSITION",
            {"argument": argument, "agent": self.agent_name},
            context_refs=context_refs, confidence=confidence)

    async def challenge(self, room_id: str, challenge: str, target_message_id: str,
                        confidence: float = 0.8) -> dict:
        return await self.post(room_id, "CHALLENGE",
            {"challenge": challenge, "agent": self.agent_name},
            context_refs=[target_message_id], confidence=confidence)

    async def respond(self, room_id: str, response: str, to_message_id: str,
                      confidence: float = 0.8) -> dict:
        return await self.post(room_id, "RESPONSE",
            {"response": response, "agent": self.agent_name},
            context_refs=[to_message_id], confidence=confidence)

    async def verdict(self, room_id: str, decision: str, reasoning: str,
                      confidence: float, recommended_actions: list[str],
                      dissenting_views: list[str] = None) -> dict:
        return await self.post(room_id, "VERDICT", {
            "decision": decision,
            "reasoning": reasoning,
            "confidence": confidence,
            "recommended_actions": recommended_actions,
            "dissenting_views": dissenting_views or [],
            "agent": self.agent_name,
            "timestamp": datetime.utcnow().isoformat()
        }, confidence=confidence)

    async def get_messages(self, room_id: str, limit: int = 100) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/rooms/{room_id}/messages",
                params={"limit": limit}, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Context Store ────────────────────────────────────
    async def set_context(self, room_id: str, key: str, value: Any) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms/{room_id}/context",
                json={"key": key, "value": value}, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_context(self, room_id: str, key: str = None) -> Any:
        async with httpx.AsyncClient() as client:
            params = {"key": key} if key else {}
            resp = await client.get(f"{self.base_url}/rooms/{room_id}/context",
                params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Recruitment ──────────────────────────────────────
    async def recruit(self, room_id: str, skills_needed: list[str],
                      reason: str = None) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/rooms/{room_id}/recruit",
                json={
                    "id": f"rec_{secrets.token_hex(8)}",
                    "skills_needed": skills_needed,
                    "reason": reason
                },
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def accept_recruitment(self, recruitment_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/recruitment/{recruitment_id}/accept",
                headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Agent Discovery ──────────────────────────────────
    async def find_agents(self, skill: str = None) -> list[dict]:
        async with httpx.AsyncClient() as client:
            params = {"skill": skill} if skill else {}
            resp = await client.get(f"{self.base_url}/agents",
                params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Audit ────────────────────────────────────────────
    async def get_audit(self, room_id: str = None, limit: int = 200) -> list[dict]:
        async with httpx.AsyncClient() as client:
            params = {}
            if room_id:
                params["room_id"] = room_id
            params["limit"] = limit
            resp = await client.get(f"{self.base_url}/audit",
                params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
