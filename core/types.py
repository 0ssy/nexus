import os
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────
class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/nexus")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    SECRET_KEY = os.getenv("SECRET_KEY", "nexus-secret-change-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_HOURS = 24
    MAX_ROOM_AGENTS = 20
    RECRUITMENT_TIMEOUT_SECONDS = 30

# ── Enums ────────────────────────────────────────────────
class AgentStatus(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"

class RoomStatus(str, Enum):
    OPEN = "open"
    DELIBERATING = "deliberating"
    DECIDED = "decided"
    CLOSED = "closed"

class MessageType(str, Enum):
    POSITION = "POSITION"       # Agent states its view
    CHALLENGE = "CHALLENGE"     # Agent challenges another's view
    RESPONSE = "RESPONSE"       # Agent responds to a challenge
    VERDICT = "VERDICT"         # Judge delivers final verdict
    RECRUIT = "RECRUIT"         # Request to recruit an agent
    SYSTEM = "SYSTEM"           # System-level message
    JOIN = "JOIN"               # Agent joined room
    LEAVE = "LEAVE"             # Agent left room
    CONTEXT = "CONTEXT"         # Context store update

class AgentRole(str, Enum):
    PARTICIPANT = "participant"
    JUDGE = "judge"
    ADVOCATE = "advocate"
    RECRUITER = "recruiter"
    INTAKE = "intake"
    AUDITOR = "auditor"

class AuditEvent(str, Enum):
    AGENT_REGISTERED = "AGENT_REGISTERED"
    AGENT_CONNECTED = "AGENT_CONNECTED"
    AGENT_DISCONNECTED = "AGENT_DISCONNECTED"
    ROOM_CREATED = "ROOM_CREATED"
    ROOM_CLOSED = "ROOM_CLOSED"
    AGENT_JOINED_ROOM = "AGENT_JOINED_ROOM"
    AGENT_LEFT_ROOM = "AGENT_LEFT_ROOM"
    MESSAGE_POSTED = "MESSAGE_POSTED"
    CONTEXT_UPDATED = "CONTEXT_UPDATED"
    RECRUITMENT_REQUESTED = "RECRUITMENT_REQUESTED"
    RECRUITMENT_FULFILLED = "RECRUITMENT_FULFILLED"
    RECRUITMENT_REJECTED = "RECRUITMENT_REJECTED"
    VERDICT_DELIVERED = "VERDICT_DELIVERED"

# ── Pydantic Models ──────────────────────────────────────
class AgentRegisterRequest(BaseModel):
    id: str
    name: str
    skills: list[str]
    description: Optional[str] = None
    metadata: Optional[dict] = None

class AgentInfo(BaseModel):
    id: str
    name: str
    skills: list[str]
    description: Optional[str]
    status: AgentStatus
    metadata: dict

class CreateRoomRequest(BaseModel):
    id: str
    name: str
    purpose: Optional[str] = None
    metadata: Optional[dict] = None

class RoomInfo(BaseModel):
    id: str
    name: str
    purpose: Optional[str]
    status: RoomStatus
    created_by: str
    members: list[str] = []
    metadata: dict

class PostMessageRequest(BaseModel):
    id: str
    type: MessageType
    content: dict[str, Any]
    context_refs: Optional[list[str]] = []
    confidence: Optional[float] = None
    metadata: Optional[dict] = None

class Message(BaseModel):
    id: str
    room_id: str
    from_agent: str
    type: MessageType
    content: dict[str, Any]
    context_refs: list[str]
    confidence: Optional[float]
    created_at: str
    metadata: dict

class RecruitRequest(BaseModel):
    id: str
    skills_needed: list[str]
    reason: Optional[str] = None

class ContextEntry(BaseModel):
    key: str
    value: Any

class WebSocketMessage(BaseModel):
    event: str
    data: dict[str, Any]

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    agent_id: str
