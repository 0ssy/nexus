"""
NEXUS Middleware Adapter
========================
Drop-in connector for existing agent frameworks.
Lets developers keep their current setup and route
consensus-building through NEXUS.

Supported:
- Raw OpenAI / Anthropic API outputs
- LangChain / LangGraph agent outputs
- CrewAI agent outputs
- Any Python function that returns a string

Usage:
    from sdk.middleware import NexusMiddleware

    nexus = NexusMiddleware(api_url="http://localhost:8000")
    await nexus.setup("my_agent", ["analysis", "legal"])

    # Pass your existing agent outputs directly
    result = await nexus.collaborate([
        {"agent": "legal_bot",   "output": legal_bot.run(case)},
        {"agent": "finance_bot", "output": finance_bot.run(case)},
        {"agent": "risk_bot",    "output": risk_bot.run(case)},
    ])

    print(result.verdict)
    print(result.tokens_saved)
    print(result.loops_blocked)
"""

import httpx
import secrets
import asyncio
from dataclasses import dataclass
from typing import Optional

@dataclass
class CollaborationResult:
    verdict: str
    confidence: float
    room_id: str
    tokens_saved: int
    loops_blocked: int
    messages_filtered: int
    agents_participated: int
    recommended_actions: list[str]
    dissenting_views: list[str]
    audit_events: int
    run_id: Optional[str] = None
    error: Optional[str] = None

class NexusMiddleware:
    """
    Drop-in middleware layer for existing agent frameworks.
    Routes agent outputs through NEXUS for consensus building.
    """
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url.rstrip("/")
        self.token: Optional[str] = None
        self.agent_id: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=120.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def setup(self, agent_id: str, skills: list[str],
                    name: str = None, description: str = None) -> str:
        """
        Register this middleware instance with NEXUS.
        Returns the API key.
        """
        unique_id = f"{agent_id}_{secrets.token_hex(4)}"
        self.agent_id = unique_id

        resp = await self._http.post(f"{self.api_url}/agents/register", json={
            "id": unique_id,
            "name": name or f"Middleware({agent_id})",
            "skills": skills,
            "description": description or "NEXUS middleware adapter"
        })
        resp.raise_for_status()
        data = resp.json()
        self.token = data["access_token"]
        return data["api_key"]

    async def collaborate(self, agent_outputs: list[dict],
                          case_context: str = "",
                          room_name: str = None) -> CollaborationResult:
        """
        Main entry point. Takes outputs from existing agents
        and routes them through NEXUS for consensus building.

        agent_outputs format:
        [
            {"agent": "my_legal_agent", "output": "...", "confidence": 0.8},
            {"agent": "my_finance_agent", "output": "...", "confidence": 0.7},
        ]
        """
        if not self.token:
            raise RuntimeError("Call setup() before collaborate()")

        room_id = f"mw_{secrets.token_hex(8)}"
        loops_blocked = 0
        messages_filtered = 0

        # Create room
        await self._http.post(f"{self.api_url}/rooms", json={
            "id": room_id,
            "name": room_name or "NEXUS Collaboration",
            "purpose": case_context[:500] if case_context else "Middleware collaboration"
        }, headers=self._headers())

        # Join room
        await self._http.post(
            f"{self.api_url}/rooms/{room_id}/join",
            params={"role": "recruiter"},
            headers=self._headers()
        )

        # Post case context
        if case_context:
            await self._post_message(room_id, "SYSTEM", {
                "context": case_context,
                "source": "middleware"
            })

        # Register and post each agent's output
        registered_agents = []
        for agent_output in agent_outputs:
            agent_name = agent_output.get("agent", f"agent_{secrets.token_hex(4)}")
            output = agent_output.get("output", "")
            confidence = agent_output.get("confidence", 0.75)

            if not output or len(str(output)) < 10:
                continue

            # Register agent
            agent_id = f"mw_{agent_name}_{secrets.token_hex(4)}"
            try:
                reg_resp = await self._http.post(
                    f"{self.api_url}/agents/register",
                    json={
                        "id": agent_id,
                        "name": agent_name,
                        "skills": agent_output.get("skills", ["analysis"]),
                        "description": f"Middleware-connected agent: {agent_name}"
                    }
                )
                reg_resp.raise_for_status()
                agent_token = reg_resp.json()["access_token"]

                # Join room
                await self._http.post(
                    f"{self.api_url}/rooms/{room_id}/join",
                    params={"role": "participant"},
                    headers={"Authorization": f"Bearer {agent_token}"}
                )

                # Post position
                msg_resp = await self._http.post(
                    f"{self.api_url}/rooms/{room_id}/messages",
                    json={
                        "id": f"msg_{secrets.token_hex(8)}",
                        "type": "POSITION",
                        "content": {
                            "argument": str(output),
                            "agent": agent_name,
                            "source": "middleware"
                        },
                        "confidence": confidence
                    },
                    headers={"Authorization": f"Bearer {agent_token}"}
                )

                if msg_resp.status_code == 429:
                    loops_blocked += 1
                elif msg_resp.status_code == 422:
                    messages_filtered += 1
                else:
                    registered_agents.append({
                        "id": agent_id,
                        "name": agent_name,
                        "token": agent_token
                    })

            except Exception as e:
                print(f"[NEXUS Middleware] Warning: {agent_name} failed: {e}")
                continue

        # Run verdict through NEXUS
        verdict_result = await self._run_verdict(
            room_id, case_context, agent_outputs
        )

        # Get token savings
        savings = await self._get_savings(room_id)
        audit = await self._get_audit(room_id)
        telemetry = await self._get_telemetry(room_id)

        return CollaborationResult(
            verdict=verdict_result.get("verdict", "No verdict delivered"),
            confidence=verdict_result.get("confidence", 0.0),
            room_id=room_id,
            tokens_saved=savings.get("tokens_saved", 0),
            loops_blocked=loops_blocked + telemetry.get("metrics", {}).get("loops_blocked", 0),
            messages_filtered=messages_filtered + telemetry.get("metrics", {}).get("messages_filtered", 0),
            agents_participated=len(registered_agents),
            recommended_actions=verdict_result.get("recommended_actions", []),
            dissenting_views=verdict_result.get("dissenting_views", []),
            audit_events=len(audit),
            run_id=telemetry.get("run_id")
        )

    async def _post_message(self, room_id: str, msg_type: str, content: dict,
                             confidence: float = None) -> dict:
        resp = await self._http.post(
            f"{self.api_url}/rooms/{room_id}/messages",
            json={
                "id": f"msg_{secrets.token_hex(8)}",
                "type": msg_type,
                "content": content,
                "confidence": confidence
            },
            headers=self._headers()
        )
        return resp.json() if resp.status_code == 200 else {}

    async def _run_verdict(self, room_id: str,
                            case_context: str,
                            agent_outputs: list[dict]) -> dict:
        """Run the NEXUS verdict engine on the collected outputs."""
        try:
            from verdict.agents import JudgeAgent
            from dotenv import load_dotenv
            load_dotenv()

            judge = JudgeAgent()
            await judge.register()
            await judge.nexus.join_room(room_id, role="judge")

            debate_log = "\n\n".join([
                f"[{o.get('agent', 'AGENT').upper()}]: {o.get('output', '')}"
                for o in agent_outputs
            ])

            verdict = judge.deliver_verdict(case_context, debate_log)

            # Post verdict to room
            await self._http.post(
                f"{self.api_url}/rooms/{room_id}/messages",
                json={
                    "id": f"msg_{secrets.token_hex(8)}",
                    "type": "VERDICT",
                    "content": {"verdict": verdict["verdict"]},
                    "confidence": 0.85
                },
                headers=self._headers()
            )

            return {
                "verdict": verdict["verdict"],
                "confidence": 0.85,
                "recommended_actions": [],
                "dissenting_views": []
            }
        except Exception as e:
            return {
                "verdict": f"Verdict engine error: {e}",
                "confidence": 0.0,
                "recommended_actions": [],
                "dissenting_views": []
            }

    async def _get_savings(self, room_id: str) -> dict:
        try:
            resp = await self._http.get(
                f"{self.api_url}/rooms/{room_id}/context/savings",
                headers=self._headers()
            )
            return resp.json() if resp.status_code == 200 else {}
        except:
            return {}

    async def _get_audit(self, room_id: str) -> list:
        try:
            resp = await self._http.get(
                f"{self.api_url}/audit",
                params={"room_id": room_id},
                headers=self._headers()
            )
            return resp.json() if resp.status_code == 200 else []
        except:
            return []

    async def _get_telemetry(self, room_id: str) -> dict:
        try:
            resp = await self._http.get(
                f"{self.api_url}/rooms/{room_id}/telemetry",
                headers=self._headers()
            )
            return resp.json() if resp.status_code == 200 else {}
        except:
            return {}

    async def close(self):
        await self._http.aclose()


# ── Sync wrapper for non-async codebases ─────────────────
class NexusMiddlewareSync:
    """
    Synchronous wrapper for codebases that don't use async/await.
    Drop this in anywhere and call it like a regular function.
    """
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        self._async = NexusMiddleware(api_url)

    def setup(self, agent_id: str, skills: list[str], **kwargs) -> str:
        return asyncio.run(self._async.setup(agent_id, skills, **kwargs))

    def collaborate(self, agent_outputs: list[dict],
                    case_context: str = "", **kwargs) -> CollaborationResult:
        return asyncio.run(self._async.collaborate(
            agent_outputs, case_context, **kwargs
        ))