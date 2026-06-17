"""
Trust Query Interface
Simple way to look up trust scores for businesses.
This is what eventually becomes the product.

Usage:
    python -m trust.query "Pizza Hut"
    python -m trust.query --country GB --risk high
    python -m trust.query --stats
"""

import asyncio
import asyncpg
import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from trust.database import get_pool, close

load_dotenv()

async def lookup_business(name: str) -> dict:
    """Look up trust score for a specific business by name."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Search for business
        rows = await conn.fetch(
            """
            SELECT 
                b.id, b.name, b.country, b.jurisdiction,
                b.sector, b.source, b.first_seen,
                ts.score, ts.confidence, ts.risk_level,
                ts.trend, ts.signal_count, ts.negative_signals,
                ts.positive_signals, ts.notes, ts.calculated_at
            FROM businesses b
            LEFT JOIN trust_scores ts ON ts.business_id = b.id
            WHERE b.name ILIKE $1
            ORDER BY ts.score ASC NULLS LAST
            LIMIT 5
            """,
            f"%{name}%"
        )
        return [dict(r) for r in rows]

async def get_risky_businesses(
    country: str = None,
    risk_level: str = None,
    limit: int = 20
) -> list:
    """Get businesses filtered by country and/or risk level."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT 
                b.name, b.country, b.sector,
                ts.score, ts.risk_level, ts.trend,
                ts.signal_count, ts.confidence,
                ts.calculated_at
            FROM businesses b
            JOIN trust_scores ts ON ts.business_id = b.id
            WHERE 1=1
        """
        params = []

        if country:
            params.append(country.upper())
            query += f" AND b.country = ${len(params)}"

        if risk_level:
            params.append(risk_level.lower())
            query += f" AND ts.risk_level = ${len(params)}"

        query += f" ORDER BY ts.score ASC LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

async def get_recent_signals(business_id: int, limit: int = 10) -> list:
    """Get recent signals for a business."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT signal_type, signal_category, source,
                   title, signal_date, weight
            FROM signals
            WHERE business_id = $1
            ORDER BY signal_date DESC
            LIMIT $2
            """,
            business_id, limit
        )
        return [dict(r) for r in rows]

def format_score_bar(score: float, width: int = 20) -> str:
    """Format a visual score bar."""
    if score is None:
        return "░" * width + " (unscored)"
    filled = int((score / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    return bar

def format_risk_label(risk_level: str) -> str:
    """Format risk level with visual indicator."""
    indicators = {
        "critical": "🔴 CRITICAL",
        "high":     "🟠 HIGH",
        "medium":   "🟡 MEDIUM",
        "low":      "🟢 LOW",
        "trusted":  "✅ TRUSTED",
        "unknown":  "⬜ UNKNOWN"
    }
    return indicators.get(risk_level, "⬜ UNKNOWN")

async def run_query(args: list):
    """Main query runner."""

    if not args or args[0] == "--help":
        print("""
Trust Query Interface
Usage:
  python -m trust.query "Company Name"     Search by name
  python -m trust.query --risk critical    Filter by risk level
  python -m trust.query --country GB       Filter by country
  python -m trust.query --stats            Database statistics
        """)
        return

    if args[0] == "--stats":
        pool = await get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM businesses")
            scored = await conn.fetchval("SELECT COUNT(*) FROM trust_scores")
            signals = await conn.fetchval("SELECT COUNT(*) FROM signals")
            critical = await conn.fetchval(
                "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'critical'"
            )
            high = await conn.fetchval(
                "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'high'"
            )
            trusted = await conn.fetchval(
                "SELECT COUNT(*) FROM trust_scores WHERE risk_level = 'trusted'"
            )

        print(f"\n{'='*50}")
        print(f"TRUST DATABASE STATISTICS")
        print(f"{'='*50}")
        print(f"Businesses tracked:  {total}")
        print(f"Businesses scored:   {scored}")
        print(f"Signals collected:   {signals}")
        print(f"\nRisk Distribution:")
        print(f"  🔴 Critical: {critical}")
        print(f"  🟠 High:     {high}")
        print(f"  ✅ Trusted:  {trusted}")
        await close()
        return

    # Parse flags
    country = None
    risk = None
    search_name = None

    i = 0
    while i < len(args):
        if args[i] == "--country" and i + 1 < len(args):
            country = args[i + 1]
            i += 2
        elif args[i] == "--risk" and i + 1 < len(args):
            risk = args[i + 1]
            i += 2
        else:
            search_name = args[i]
            i += 1

    if search_name:
        # Name lookup
        print(f"\nSearching for: '{search_name}'")
        print("─" * 50)

        results = await lookup_business(search_name)

        if not results:
            print(f"No businesses found matching '{search_name}'")
            await close()
            return

        for r in results:
            score = r.get("score")
            risk_level = r.get("risk_level", "unknown")
            bar = format_score_bar(float(score) if score else 50.0)
            risk_label = format_risk_label(risk_level)

            print(f"\n{r['name']}")
            print(f"  Country:     {r.get('country', 'Unknown')}")
            print(f"  Score:       {bar} {float(score):.1f}/100" if score else "  Score:       Not yet scored")
            print(f"  Risk:        {risk_label}")
            print(f"  Confidence:  {float(r['confidence']):.0%}" if r.get('confidence') else "  Confidence:  N/A")
            print(f"  Trend:       {r.get('trend', 'unknown').upper()}")
            print(f"  Signals:     {r.get('signal_count', 0)}")
            print(f"  Notes:       {r.get('notes', 'None')}")
            print(f"  Source:      {r.get('source', 'Unknown')}")

            # Show recent signals
            if r.get('id') and r.get('signal_count', 0) > 0:
                signals = await get_recent_signals(r['id'], limit=3)
                if signals:
                    print(f"  Recent signals:")
                    for s in signals:
                        cat = "[-]" if s['signal_category'] == 'negative' else "[+]"
                        print(f"    {cat} {s['signal_type']}: {s['title'][:60]}")

    elif country or risk:
        # Filter query
        filter_desc = []
        if country:
            filter_desc.append(f"country={country}")
        if risk:
            filter_desc.append(f"risk={risk}")
        print(f"\nFiltering by: {', '.join(filter_desc)}")
        print("─" * 50)

        results = await get_risky_businesses(country=country, risk_level=risk)

        if not results:
            print("No businesses found matching filters")
            await close()
            return

        for r in results:
            score = float(r['score']) if r.get('score') else 50.0
            bar = format_score_bar(score, width=10)
            risk_label = format_risk_label(r.get('risk_level', 'unknown'))
            print(f"{r['name'][:35]:35} {bar} {score:5.1f} {risk_label}")

    await close()

if __name__ == "__main__":
    asyncio.run(run_query(sys.argv[1:]))