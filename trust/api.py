"""
Nanobits Trust API
FastAPI endpoint that exposes trust scores to the world.
This is the product — what businesses and developers pay to query.

Endpoints:
    GET  /trust/health              — API health check
    GET  /trust/business/{name}     — Look up trust score by name
    GET  /trust/search?q=name       — Search businesses
    GET  /trust/risk/{level}        — Get businesses by risk level
    GET  /trust/stats               — Database statistics
    POST /trust/report              — Submit a business for monitoring
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Create a sub-application for the trust API
trust_app = FastAPI(
    title="Nanobits Trust API",
    description="Global business trust intelligence — powered by Nanobits",
    version="0.1.0"
)

trust_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# ── Health ────────────────────────────────────────────────
@trust_app.get("/health")
async def health():
    """API health check."""
    return {
        "status": "online",
        "service": "Nanobits Trust API",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

# ── Business Lookup ───────────────────────────────────────
@trust_app.get("/business/{name}")
async def get_business_trust(name: str):
    """
    Look up trust score for a business by name.
    Returns trust score, risk level, signals, and trend.
    """
    from trust.database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                b.id, b.name, b.country, b.jurisdiction,
                b.sector, b.source, b.first_seen,
                ts.score, ts.confidence, ts.risk_level,
                ts.trend, ts.signal_count, ts.negative_signals,
                ts.positive_signals, ts.neutral_signals,
                ts.notes, ts.calculated_at
            FROM businesses b
            LEFT JOIN trust_scores ts ON ts.business_id = b.id
            WHERE b.name ILIKE $1
            ORDER BY ts.score ASC NULLS LAST
            LIMIT 5
            """,
            f"%{name}%"
        )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No businesses found matching '{name}'"
        )

    results = []
    for r in rows:
        score = float(r["score"]) if r["score"] is not None else None
        results.append({
            "name": r["name"],
            "country": r["country"],
            "jurisdiction": r["jurisdiction"],
            "sector": r["sector"],
            "trust_score": score,
            "risk_level": r["risk_level"] or "unknown",
            "confidence": float(r["confidence"]) if r["confidence"] else 0.0,
            "trend": r["trend"] or "stable",
            "signal_count": r["signal_count"] or 0,
            "negative_signals": r["negative_signals"] or 0,
            "positive_signals": r["positive_signals"] or 0,
            "notes": r["notes"],
            "source": r["source"],
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_scored": r["calculated_at"].isoformat() if r["calculated_at"] else None
        })

    return {
        "query": name,
        "results": results,
        "count": len(results),
        "powered_by": "Nanobits Trust Intelligence"
    }

# ── Search ────────────────────────────────────────────────
@trust_app.get("/search")
async def search_businesses(
    q: str = Query(..., description="Business name to search"),
    country: Optional[str] = Query(None, description="Filter by country code (e.g. GB, KE)"),
    limit: int = Query(10, le=50)
):
    """Search businesses in the trust database."""
    from trust.database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        if country:
            rows = await conn.fetch(
                """
                SELECT b.name, b.country, ts.score, ts.risk_level,
                       ts.signal_count, ts.confidence
                FROM businesses b
                LEFT JOIN trust_scores ts ON ts.business_id = b.id
                WHERE b.name ILIKE $1 AND b.country = $2
                ORDER BY ts.score ASC NULLS LAST
                LIMIT $3
                """,
                f"%{q}%", country.upper(), limit
            )
        else:
            rows = await conn.fetch(
                """
                SELECT b.name, b.country, ts.score, ts.risk_level,
                       ts.signal_count, ts.confidence
                FROM businesses b
                LEFT JOIN trust_scores ts ON ts.business_id = b.id
                WHERE b.name ILIKE $1
                ORDER BY ts.score ASC NULLS LAST
                LIMIT $2
                """,
                f"%{q}%", limit
            )

    return {
        "query": q,
        "country_filter": country,
        "results": [
            {
                "name": r["name"],
                "country": r["country"],
                "trust_score": float(r["score"]) if r["score"] else None,
                "risk_level": r["risk_level"] or "unknown",
                "signal_count": r["signal_count"] or 0,
                "confidence": float(r["confidence"]) if r["confidence"] else 0.0
            }
            for r in rows
        ],
        "count": len(rows)
    }

# ── Risk Filter ───────────────────────────────────────────
@trust_app.get("/risk/{level}")
async def get_by_risk(
    level: str,
    country: Optional[str] = Query(None),
    limit: int = Query(20, le=100)
):
    """
    Get businesses by risk level.
    Levels: critical, high, medium, low, trusted
    """
    valid_levels = ["critical", "high", "medium", "low", "trusted", "unknown"]
    if level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid risk level. Choose from: {', '.join(valid_levels)}"
        )

    from trust.database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        if country:
            rows = await conn.fetch(
                """
                SELECT b.name, b.country, b.sector,
                       ts.score, ts.risk_level, ts.trend,
                       ts.signal_count, ts.confidence, ts.calculated_at
                FROM businesses b
                JOIN trust_scores ts ON ts.business_id = b.id
                WHERE ts.risk_level = $1 AND b.country = $2
                ORDER BY ts.score ASC
                LIMIT $3
                """,
                level, country.upper(), limit
            )
        else:
            rows = await conn.fetch(
                """
                SELECT b.name, b.country, b.sector,
                       ts.score, ts.risk_level, ts.trend,
                       ts.signal_count, ts.confidence, ts.calculated_at
                FROM businesses b
                JOIN trust_scores ts ON ts.business_id = b.id
                WHERE ts.risk_level = $1
                ORDER BY ts.score ASC
                LIMIT $2
                """,
                level, limit
            )

    return {
        "risk_level": level,
        "country_filter": country,
        "results": [
            {
                "name": r["name"],
                "country": r["country"],
                "sector": r["sector"],
                "trust_score": float(r["score"]),
                "trend": r["trend"],
                "signal_count": r["signal_count"],
                "confidence": float(r["confidence"]),
                "last_scored": r["calculated_at"].isoformat() if r["calculated_at"] else None
            }
            for r in rows
        ],
        "count": len(rows)
    }

# ── Stats ─────────────────────────────────────────────────
@trust_app.get("/stats")
async def get_stats():
    """Database statistics — how much we know."""
    from trust.database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        businesses = await conn.fetchval("SELECT COUNT(*) FROM businesses")
        signals = await conn.fetchval("SELECT COUNT(*) FROM signals")
        scored = await conn.fetchval("SELECT COUNT(*) FROM trust_scores")
        prices = await conn.fetchval("SELECT COUNT(*) FROM market_prices")
        critical = await conn.fetchval(
            "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'critical'"
        )
        high = await conn.fetchval(
            "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'high'"
        )
        trusted = await conn.fetchval(
            "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'trusted'"
        )
        countries = await conn.fetchval(
            "SELECT COUNT(DISTINCT country) FROM businesses"
        )

    return {
        "nanobits_trust_database": {
            "businesses_tracked": businesses,
            "signals_collected": signals,
            "businesses_scored": scored,
            "market_prices": prices,
            "countries_covered": countries,
            "risk_distribution": {
                "critical": critical,
                "high": high,
                "trusted": trusted
            }
        },
        "as_of": datetime.utcnow().isoformat()
    }

# ── Report ────────────────────────────────────────────────
@trust_app.post("/report")
async def report_business(payload: dict):
    """
    Submit a business for monitoring.
    Anyone can flag a business they want tracked.
    """
    name = payload.get("name", "").strip()
    country = payload.get("country", "").strip().upper()
    reason = payload.get("reason", "").strip()

    if not name or not country:
        raise HTTPException(
            status_code=400,
            detail="Both 'name' and 'country' are required"
        )

    from trust.database import insert_business
    business_id = await insert_business(
        name=name,
        country=country,
        source="user_report",
        metadata={
            "reported_reason": reason,
            "reported_at": datetime.utcnow().isoformat()
        }
    )

    return {
        "status": "accepted",
        "message": f"{name} has been added to monitoring queue",
        "business_id": business_id,
        "note": "Trust score will be calculated as signals are collected"
    }