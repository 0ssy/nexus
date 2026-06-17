"""
Trust Layer — Database Connection
Handles all reads and writes to the trust database.
Shared Railway PostgreSQL instance, separate trust tables.
"""

import asyncpg
import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None

async def get_pool():
    """Get or create database connection pool."""
    global _pool
    if _pool is None:
        ssl_mode = "require" if DATABASE_URL and "railway" in DATABASE_URL else None
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            ssl=ssl_mode,
            server_settings={"search_path": "public"}
        )
    return _pool

async def insert_business(
    name: str,
    country: str,
    jurisdiction: str = None,
    sector: str = None,
    city: str = None,
    registration_number: str = None,
    source: str = None,
    source_url: str = None,
    metadata: dict = None
) -> int:
    """
    Insert a business or return existing ID if already tracked.
    Returns business ID.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check if already exists
        existing = await conn.fetchrow(
            """
            SELECT id FROM businesses
            WHERE name ILIKE $1 AND country = $2
            LIMIT 1
            """,
            name, country
        )
        if existing:
            # Update last_updated
            await conn.execute(
                "UPDATE businesses SET last_updated = NOW() WHERE id = $1",
                existing["id"]
            )
            return existing["id"]

        # Insert new
        row = await conn.fetchrow(
            """
            INSERT INTO businesses
            (name, country, jurisdiction, sector, city,
             registration_number, source, source_url, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            name, country, jurisdiction, sector, city,
            registration_number, source, source_url,
            json.dumps(metadata) if metadata else None
        )
        return row["id"]

async def insert_signal(
    business_id: int,
    signal_type: str,
    signal_category: str,
    source: str,
    title: str = None,
    content: str = None,
    signal_date: datetime = None,
    source_url: str = None,
    weight: float = 0.0,
    metadata: dict = None
) -> int:
    """Insert a signal for a business. Returns signal ID."""
    # Normalize signal_date — strip timezone for PostgreSQL TIMESTAMP column
    if signal_date is None:
        signal_date = datetime.utcnow()
    elif signal_date.tzinfo is not None:
        signal_date = signal_date.replace(tzinfo=None)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO signals
            (business_id, signal_type, signal_category, source,
             title, content, signal_date, source_url, weight, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            business_id, signal_type, signal_category, source,
            title, content, signal_date, source_url, weight,
            json.dumps(metadata) if metadata else None
        )
        return row["id"]

async def get_signal_weight(signal_type: str) -> float:
    """Get the algorithmic weight for a signal type."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT weight FROM signal_weights WHERE signal_type = $1",
            signal_type
        )
        return float(row["weight"]) if row else 0.0

async def get_businesses(country: str = None, limit: int = 100) -> list:
    """Get tracked businesses, optionally filtered by country."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if country:
            rows = await conn.fetch(
                "SELECT * FROM businesses WHERE country = $1 LIMIT $2",
                country, limit
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM businesses LIMIT $1", limit
            )
        return [dict(r) for r in rows]

async def get_signals_for_business(business_id: int) -> list:
    """Get all signals for a specific business."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM signals
            WHERE business_id = $1
            ORDER BY signal_date DESC
            """,
            business_id
        )
        return [dict(r) for r in rows]

async def upsert_trust_score(
    business_id: int,
    score: float,
    confidence: float,
    signal_count: int,
    negative_signals: int,
    positive_signals: int,
    neutral_signals: int,
    risk_level: str,
    trend: str,
    notes: str = None
):
    """Insert or update trust score for a business."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO trust_scores
            (business_id, score, confidence, signal_count,
             negative_signals, positive_signals, neutral_signals,
             risk_level, trend, notes, calculated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (business_id) DO UPDATE SET
                score = EXCLUDED.score,
                confidence = EXCLUDED.confidence,
                signal_count = EXCLUDED.signal_count,
                negative_signals = EXCLUDED.negative_signals,
                positive_signals = EXCLUDED.positive_signals,
                neutral_signals = EXCLUDED.neutral_signals,
                risk_level = EXCLUDED.risk_level,
                trend = EXCLUDED.trend,
                notes = EXCLUDED.notes,
                calculated_at = NOW()
            """,
            business_id, score, confidence, signal_count,
            negative_signals, positive_signals, neutral_signals,
            risk_level, trend, notes
        )

async def insert_market_price(
    commodity: str,
    price: float,
    currency: str,
    unit: str,
    market: str,
    country: str,
    source: str,
    source_url: str = None,
    metadata: dict = None
):
    """Insert a market price data point."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO market_prices
            (commodity, price, currency, unit, market,
             country, source, source_url, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            commodity, price, currency, unit, market,
            country, source, source_url,
            json.dumps(metadata) if metadata else None
        )

async def get_database_stats() -> dict:
    """Get current stats on what's in the trust database."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        businesses = await conn.fetchval("SELECT COUNT(*) FROM businesses")
        signals = await conn.fetchval("SELECT COUNT(*) FROM signals")
        scored = await conn.fetchval("SELECT COUNT(*) FROM trust_scores")
        prices = await conn.fetchval("SELECT COUNT(*) FROM market_prices")
        negative = await conn.fetchval(
            "SELECT COUNT(*) FROM signals WHERE signal_category = 'negative'"
        )
        return {
            "businesses_tracked": businesses,
            "signals_collected": signals,
            "businesses_scored": scored,
            "market_prices": prices,
            "negative_signals": negative
        }

async def close():
    """Close the database pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

if __name__ == "__main__":
    async def test():
        print("Testing trust database connection...")
        stats = await get_database_stats()
        print(f"✓ Connected successfully")
        print(f"  Businesses tracked: {stats['businesses_tracked']}")
        print(f"  Signals collected:  {stats['signals_collected']}")
        print(f"  Businesses scored:  {stats['businesses_scored']}")
        print(f"  Market prices:      {stats['market_prices']}")
        await close()

    asyncio.run(test())