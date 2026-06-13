import asyncpg
import redis.asyncio as aioredis
from core.types import Config
import json
import os
from pathlib import Path

_db_pool = None
_redis = None
_schema_initialized = False

async def get_db():
    global _db_pool, _schema_initialized
    if _db_pool is None:
        _ssl_mode = "require" if "railway" in Config.DATABASE_URL or os.getenv("RAILWAY_ENVIRONMENT") else None
        _db_pool = await asyncpg.create_pool(
            Config.DATABASE_URL,
            min_size=2,
            max_size=10,
            ssl=_ssl_mode
        )
    if not _schema_initialized:
        async with _db_pool.acquire() as conn:
            schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
            await conn.execute(schema_path.read_text(encoding="utf-8"))
        _schema_initialized = True
    return _db_pool

async def get_redis():
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(Config.REDIS_URL, decode_responses=True)
    return _redis

async def close_connections():
    global _db_pool, _redis
    if _db_pool:
        await _db_pool.close()
    if _redis:
        await _redis.close()

# ── Agent Queries ────────────────────────────────────────
async def db_register_agent(pool, agent_id, name, skills, description, api_key_hash, metadata):
    async with pool.acquire() as conn:
        # Ensure skills is a proper list
        if isinstance(skills, str):
            skills = json.loads(skills)
        skills = list(skills)
        await conn.execute("""
            INSERT INTO agents (id, name, skills, description, api_key_hash, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                skills = EXCLUDED.skills,
                description = EXCLUDED.description,
                metadata = EXCLUDED.metadata,
                last_seen = NOW()
        """, agent_id, name, skills, description, api_key_hash, json.dumps(metadata or {}))

async def db_get_agent(pool, agent_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)

async def db_update_agent_status(pool, agent_id, status):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agents SET status = $2, last_seen = NOW() WHERE id = $1",
            agent_id, str(status)
        )

# ── Room Queries ───────────────────────────────────────────
async def db_create_room(pool, room_id, name, purpose, created_by, metadata):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO rooms (id, name, purpose, created_by, metadata)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO NOTHING
        """, room_id, name, purpose, created_by, json.dumps(metadata or {}))

async def db_get_room(pool, room_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)

async def db_add_room_member(pool, room_id, agent_id, role):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO room_members (room_id, agent_id, role, left_at)
            VALUES ($1, $2, $3, NULL)
            ON CONFLICT (room_id, agent_id) DO UPDATE SET
                role = EXCLUDED.role,
                left_at = NULL
        """, room_id, agent_id, role)

async def db_remove_room_member(pool, room_id, agent_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE room_members SET left_at = NOW() WHERE room_id = $1 AND agent_id = $2",
            room_id, agent_id
        )

async def db_get_room_members(pool, room_id):
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM room_members
            WHERE room_id = $1 AND left_at IS NULL
            ORDER BY joined_at ASC
        """, room_id)

# ── Message Queries ────────────────────────────────────────
async def db_post_message(pool, message_id, room_id, from_agent, message_type, content, context_refs, confidence, metadata):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO messages (id, room_id, from_agent, type, content, context_refs, confidence, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, message_id, room_id, from_agent, str(message_type), json.dumps(content), list(context_refs or []), confidence, json.dumps(metadata or {}))

async def db_get_room_messages(pool, room_id, limit, offset):
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM messages
            WHERE room_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
        """, room_id, limit, offset)

# ── Context Queries ────────────────────────────────────────
async def db_set_context(pool, entry_id, room_id, posted_by, key, value):
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("""
            SELECT id, version
            FROM context_entries
            WHERE room_id = $1 AND key = $2
            ORDER BY updated_at DESC
            LIMIT 1
        """, room_id, key)
        if existing:
            await conn.execute("""
                UPDATE context_entries
                SET value = $2, posted_by = $3, version = $4, updated_at = NOW()
                WHERE id = $1
            """, existing["id"], json.dumps(value), posted_by, existing["version"] + 1)
        else:
            await conn.execute("""
                INSERT INTO context_entries (id, room_id, posted_by, key, value, version)
                VALUES ($1, $2, $3, $4, $5, 1)
            """, entry_id, room_id, posted_by, key, json.dumps(value))

async def db_get_context(pool, room_id, key=None):
    async with pool.acquire() as conn:
        if key is not None:
            return await conn.fetchrow("""
                SELECT *
                FROM context_entries
                WHERE room_id = $1 AND key = $2
                ORDER BY updated_at DESC
                LIMIT 1
            """, room_id, key)
        return await conn.fetch("""
            SELECT DISTINCT ON (key) *
            FROM context_entries
            WHERE room_id = $1
            ORDER BY key, version DESC
        """, room_id)

# ── Recruitment Queries ────────────────────────────────────
async def db_find_agents_by_skills(pool, skills_needed, exclude_ids=None):
    skills_needed = list(skills_needed or [])
    exclude_ids = list(exclude_ids or [])
    async with pool.acquire() as conn:
        if exclude_ids:
            return await conn.fetch("""
                SELECT * FROM agents
                WHERE status = 'available'
                  AND skills && $1::TEXT[]
                  AND NOT (id = ANY($2::TEXT[]))
                ORDER BY last_seen DESC
            """, skills_needed, exclude_ids)
        return await conn.fetch("""
            SELECT * FROM agents
            WHERE status = 'available'
              AND skills && $1::TEXT[]
            ORDER BY last_seen DESC
        """, skills_needed)

async def db_create_recruitment(pool, recruitment_id, room_id, requested_by, skills_needed, reason):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO recruitment_requests (id, room_id, requested_by, skills_needed, reason)
            VALUES ($1, $2, $3, $4, $5)
        """, recruitment_id, room_id, requested_by, list(skills_needed or []), reason)

async def db_resolve_recruitment(pool, recruitment_id, status, fulfilled_by=None):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE recruitment_requests
            SET status = $2, fulfilled_by = $3, resolved_at = NOW()
            WHERE id = $1
        """, recruitment_id, status, fulfilled_by)

# ── Audit Queries ──────────────────────────────────────────
async def db_audit(pool, event_type, agent_id, room_id, payload):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_log (event_type, agent_id, room_id, payload)
            VALUES ($1, $2, $3, $4)
        """, str(event_type), agent_id, room_id, json.dumps(payload or {}))

async def db_get_audit_log(pool, room_id=None, agent_id=None, limit=200):
    async with pool.acquire() as conn:
        if room_id and agent_id:
            return await conn.fetch("""
                SELECT * FROM audit_log
                WHERE room_id = $1 AND agent_id = $2
                ORDER BY created_at DESC
                LIMIT $3
            """, room_id, agent_id, limit)
        if room_id:
            return await conn.fetch("""
                SELECT * FROM audit_log
                WHERE room_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, room_id, limit)
        if agent_id:
            return await conn.fetch("""
                SELECT * FROM audit_log
                WHERE agent_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, agent_id, limit)
        return await conn.fetch("""
            SELECT * FROM audit_log
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)
