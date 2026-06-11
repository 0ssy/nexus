-- NEXUS Database Schema
-- Phase 1: Foundation

-- Agent Registry
CREATE TABLE IF NOT EXISTS agents (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    skills TEXT[] NOT NULL DEFAULT '{}',
    description TEXT,
    status VARCHAR(20) DEFAULT 'available', -- available, busy, offline
    api_key_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agents_skills ON agents USING GIN(skills);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

-- Rooms
CREATE TABLE IF NOT EXISTS rooms (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    purpose TEXT,
    status VARCHAR(20) DEFAULT 'open', -- open, deliberating, decided, closed
    created_by VARCHAR(100) REFERENCES agents(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Room Members
CREATE TABLE IF NOT EXISTS room_members (
    room_id VARCHAR(100) REFERENCES rooms(id),
    agent_id VARCHAR(100) REFERENCES agents(id),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    left_at TIMESTAMPTZ,
    role VARCHAR(50) DEFAULT 'participant', -- participant, judge, advocate, recruiter
    PRIMARY KEY (room_id, agent_id)
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(100) PRIMARY KEY,
    room_id VARCHAR(100) REFERENCES rooms(id),
    from_agent VARCHAR(100) REFERENCES agents(id),
    type VARCHAR(50) NOT NULL, -- POSITION, CHALLENGE, RESPONSE, VERDICT, RECRUIT, SYSTEM
    content JSONB NOT NULL,
    context_refs TEXT[] DEFAULT '{}', -- references to other message ids
    confidence FLOAT DEFAULT NULL, -- 0.0 to 1.0
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(type);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- Context Store
CREATE TABLE IF NOT EXISTS context_entries (
    id VARCHAR(100) PRIMARY KEY,
    room_id VARCHAR(100) REFERENCES rooms(id),
    posted_by VARCHAR(100) REFERENCES agents(id),
    key VARCHAR(200) NOT NULL,
    value JSONB NOT NULL,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_room ON context_entries(room_id);
CREATE INDEX IF NOT EXISTS idx_context_key ON context_entries(room_id, key);

-- Recruitment Requests
CREATE TABLE IF NOT EXISTS recruitment_requests (
    id VARCHAR(100) PRIMARY KEY,
    room_id VARCHAR(100) REFERENCES rooms(id),
    requested_by VARCHAR(100) REFERENCES agents(id),
    skills_needed TEXT[] NOT NULL,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending', -- pending, fulfilled, rejected, expired
    fulfilled_by VARCHAR(100) REFERENCES agents(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Audit Log (append only - never update or delete)
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100),
    room_id VARCHAR(100),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_room ON audit_log(room_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
