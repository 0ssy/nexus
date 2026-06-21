"""
Nanobits Trust API — Authentication
Simple API key system for controlling access.

Flow:
    1. Key is generated and stored in database
    2. Every request must include: ?api_key=xxx or X-API-Key header
    3. Free tier: 100 requests/day
    4. Paid tier: unlimited (future)

Keys are stored in the trust database.
"""

import secrets
import hashlib
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Request
from fastapi.security import APIKeyQuery, APIKeyHeader
from typing import Optional

# API key can be passed as query param or header
api_key_query = APIKeyQuery(name="api_key", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Free tier daily limit
FREE_TIER_DAILY_LIMIT = 100


def generate_api_key() -> str:
    """Generate a secure random API key."""
    return f"nb_{secrets.token_urlsafe(32)}"


def hash_key(key: str) -> str:
    """Hash an API key for storage — never store raw keys."""
    return hashlib.sha256(key.encode()).hexdigest()


async def create_api_key_table():
    """Create the API keys table if it doesn't exist."""
    from trust.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                key_hash VARCHAR(64) UNIQUE NOT NULL,
                key_prefix VARCHAR(10) NOT NULL,
                name VARCHAR(100),
                email VARCHAR(255),
                tier VARCHAR(20) DEFAULT 'free',
                daily_limit INTEGER DEFAULT 100,
                requests_today INTEGER DEFAULT 0,
                total_requests INTEGER DEFAULT 0,
                last_reset DATE DEFAULT CURRENT_DATE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used TIMESTAMP
            )
        """)


async def create_new_api_key(
    name: str,
    email: str,
    tier: str = "free"
) -> dict:
    """
    Generate and store a new API key.
    Returns the raw key — only shown once.
    """
    from trust.database import get_pool

    raw_key = generate_api_key()
    key_hash = hash_key(raw_key)
    key_prefix = raw_key[:10]  # store prefix for identification
    daily_limit = FREE_TIER_DAILY_LIMIT if tier == "free" else 999999

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO api_keys
            (key_hash, key_prefix, name, email, tier, daily_limit)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, key_hash, key_prefix, name, email, tier, daily_limit)

    return {
        "api_key": raw_key,
        "key_prefix": key_prefix,
        "tier": tier,
        "daily_limit": daily_limit,
        "message": "Save this key — it will not be shown again"
    }


async def validate_api_key(raw_key: Optional[str]) -> dict:
    """
    Validate an API key and check rate limits.
    Returns key info if valid, raises HTTPException if not.
    """
    from trust.database import get_pool

    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Get yours at nanobits.ai"
        )

    key_hash = hash_key(raw_key)
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM api_keys WHERE key_hash = $1",
            key_hash
        )

        if not row:
            raise HTTPException(
                status_code=401,
                detail="Invalid API key"
            )

        if not row["is_active"]:
            raise HTTPException(
                status_code=403,
                detail="API key has been deactivated"
            )

        # Reset daily counter if new day
        today = datetime.utcnow().date()
        if row["last_reset"] < today:
            await conn.execute("""
                UPDATE api_keys
                SET requests_today = 0, last_reset = $1
                WHERE key_hash = $2
            """, today, key_hash)
            requests_today = 0
        else:
            requests_today = row["requests_today"]

        # Check rate limit
        if requests_today >= row["daily_limit"]:
            raise HTTPException(
                status_code=429,
                detail=f"Daily limit of {row['daily_limit']} requests reached. Resets tomorrow."
            )

        # Increment counters
        await conn.execute("""
            UPDATE api_keys
            SET requests_today = requests_today + 1,
                total_requests = total_requests + 1,
                last_used = NOW()
            WHERE key_hash = $1
        """, key_hash)

        return {
            "name": row["name"],
            "email": row["email"],
            "tier": row["tier"],
            "requests_today": requests_today + 1,
            "daily_limit": row["daily_limit"],
            "remaining": row["daily_limit"] - requests_today - 1
        }


async def get_api_key(
    request: Request,
    query_key: Optional[str] = Security(api_key_query),
    header_key: Optional[str] = Security(api_key_header)
) -> dict:
    """
    FastAPI dependency — validates API key from query or header.
    Use as: key_info = Depends(get_api_key)
    """
    raw_key = query_key or header_key
    return await validate_api_key(raw_key)


async def get_optional_api_key(
    request: Request,
    query_key: Optional[str] = Security(api_key_query),
    header_key: Optional[str] = Security(api_key_header)
) -> Optional[dict]:
    """
    Optional API key — for endpoints that work with or without auth.
    Returns None if no key provided (for public endpoints).
    """
    raw_key = query_key or header_key
    if not raw_key:
        return None
    try:
        return await validate_api_key(raw_key)
    except HTTPException:
        return None