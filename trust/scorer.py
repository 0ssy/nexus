"""
Trust Scorer — Algorithmic Trust Score Calculator
Takes raw signals from the database and calculates
a trust score for each business using a weighted algorithm.

Algorithm:
    TrustScore = 50 (base) + Σ(signal_weight × recency_factor)

Recency decay:
    - Signal today     → 100% weight
    - Signal 7 days    → 80% weight
    - Signal 30 days   → 50% weight
    - Signal 90 days   → 20% weight
    - Signal 180+ days → 10% weight

Score range: 0-100
    0-20:  CRITICAL risk
    21-40: HIGH risk
    41-60: MEDIUM risk (unknown/neutral)
    61-80: LOW risk
    81-100: TRUSTED
"""

import asyncio
import asyncpg
import os
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv
from trust.database import (
    get_pool, get_signals_for_business,
    get_businesses, upsert_trust_score,
    get_database_stats
)

load_dotenv()

BASE_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

# Recency decay thresholds (days → multiplier)
RECENCY_DECAY = [
    (1,   1.0),   # today → full weight
    (7,   0.8),   # last week → 80%
    (30,  0.5),   # last month → 50%
    (90,  0.2),   # last quarter → 20%
    (180, 0.1),   # last 6 months → 10%
]

# Risk level thresholds
RISK_LEVELS = [
    (0,  20,  "critical"),
    (21, 40,  "high"),
    (41, 60,  "medium"),
    (61, 80,  "low"),
    (81, 100, "trusted"),
]

# Minimum signals needed for meaningful confidence
MIN_SIGNALS_FOR_CONFIDENCE = 3

def calculate_recency_factor(signal_date: datetime) -> float:
    """
    Calculate how much weight to give a signal based on age.
    More recent signals matter more.
    """
    if signal_date is None:
        return 0.5  # default if no date

    now = datetime.utcnow()
    age_days = (now - signal_date).days

    for threshold_days, multiplier in RECENCY_DECAY:
        if age_days <= threshold_days:
            return multiplier

    return 0.05  # very old signal — minimal weight

def determine_risk_level(score: float) -> str:
    """Convert numeric score to risk level label."""
    for min_score, max_score, level in RISK_LEVELS:
        if min_score <= score <= max_score:
            return level
    return "unknown"

def determine_trend(
    current_score: float,
    recent_signals: list,
    older_signals: list
) -> str:
    """
    Determine if trust is improving, declining, or stable.
    Compares recent signals (last 30 days) vs older signals.
    """
    if not recent_signals and not older_signals:
        return "stable"

    recent_negative = sum(
        1 for s in recent_signals
        if s.get("signal_category") == "negative"
    )
    recent_positive = sum(
        1 for s in recent_signals
        if s.get("signal_category") == "positive"
    )
    older_negative = sum(
        1 for s in older_signals
        if s.get("signal_category") == "negative"
    )
    older_positive = sum(
        1 for s in older_signals
        if s.get("signal_category") == "positive"
    )

    recent_net = recent_positive - recent_negative
    older_net = older_positive - older_negative

    if recent_net > older_net:
        return "improving"
    elif recent_net < older_net:
        return "declining"
    else:
        return "stable"

def calculate_confidence(signal_count: int, signal_diversity: int) -> float:
    """
    Calculate confidence in the trust score.
    More signals + more diverse sources = higher confidence.

    confidence: 0.0 - 1.0
    """
    if signal_count == 0:
        return 0.0

    # Base confidence from signal count
    count_confidence = min(signal_count / 10, 0.7)

    # Bonus for source diversity
    diversity_bonus = min(signal_diversity / 5, 0.3)

    return round(min(count_confidence + diversity_bonus, 1.0), 2)

def score_business(signals: list) -> dict:
    """
    Calculate trust score for a single business
    based on its signals.

    Returns scoring result dict.
    """
    if not signals:
        return {
            "score": BASE_SCORE,
            "confidence": 0.0,
            "signal_count": 0,
            "negative_signals": 0,
            "positive_signals": 0,
            "neutral_signals": 0,
            "risk_level": "unknown",
            "trend": "stable",
            "notes": "No signals collected yet"
        }

    score = BASE_SCORE
    negative_count = 0
    positive_count = 0
    neutral_count = 0
    sources = set()

    # Split signals by recency for trend calculation
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_signals = []
    older_signals = []

    for signal in signals:
        signal_date = signal.get("signal_date")
        weight = float(signal.get("weight", 0.0))
        category = signal.get("signal_category", "neutral")
        source = signal.get("source", "unknown")

        sources.add(source)

        # Calculate recency factor
        recency = calculate_recency_factor(signal_date)

        # Apply weighted score adjustment
        adjusted_weight = weight * recency * 100  # scale to score points
        score += adjusted_weight

        # Count by category
        if category == "negative":
            negative_count += 1
        elif category == "positive":
            positive_count += 1
        else:
            neutral_count += 1

        # Sort into recent/older for trend
        if signal_date and signal_date > thirty_days_ago:
            recent_signals.append(signal)
        else:
            older_signals.append(signal)

    # Clamp score to 0-100
    score = max(MIN_SCORE, min(MAX_SCORE, score))

    # Calculate confidence
    confidence = calculate_confidence(len(signals), len(sources))

    # Determine risk level and trend
    risk_level = determine_risk_level(score)
    trend = determine_trend(score, recent_signals, older_signals)

    # Build notes
    notes_parts = []
    if negative_count > 0:
        notes_parts.append(f"{negative_count} negative signals")
    if positive_count > 0:
        notes_parts.append(f"{positive_count} positive signals")
    if len(sources) > 1:
        notes_parts.append(f"from {len(sources)} sources")
    notes = ", ".join(notes_parts) if notes_parts else "Signals processed"

    return {
        "score": round(score, 2),
        "confidence": confidence,
        "signal_count": len(signals),
        "negative_signals": negative_count,
        "positive_signals": positive_count,
        "neutral_signals": neutral_count,
        "risk_level": risk_level,
        "trend": trend,
        "notes": notes
    }

async def run_scorer():
    """
    Main function — scores all businesses in the database
    that have unprocessed signals.
    """
    print("\n" + "="*60)
    print("TRUST SCORER — Calculating Business Trust Scores")
    print("="*60)

    # Get all businesses
    businesses = await get_businesses(limit=1000)
    print(f"\nBusinesses to score: {len(businesses)}")

    if not businesses:
        print("[INFO] No businesses in database yet.")
        print("       Run a collector first.")
        return []

    scored = []
    skipped = []

    for i, business in enumerate(businesses, 1):
        business_id = business["id"]
        name = business["name"]

        # Get all signals for this business
        signals = await get_signals_for_business(business_id)

        if not signals:
            skipped.append(name)
            continue

        # Calculate trust score
        result = score_business(signals)

        # Save to database
        await upsert_trust_score(
            business_id=business_id,
            score=result["score"],
            confidence=result["confidence"],
            signal_count=result["signal_count"],
            negative_signals=result["negative_signals"],
            positive_signals=result["positive_signals"],
            neutral_signals=result["neutral_signals"],
            risk_level=result["risk_level"],
            trend=result["trend"],
            notes=result["notes"]
        )

        scored.append({
            "name": name,
            "score": result["score"],
            "risk_level": result["risk_level"],
            "signals": result["signal_count"],
            "confidence": result["confidence"]
        })

        if i % 10 == 0:
            print(f"  Scored {i}/{len(businesses)}...")

    # Display results
    print(f"\n{'='*60}")
    print(f"SCORING COMPLETE")
    print(f"{'='*60}")
    print(f"Scored:  {len(scored)}")
    print(f"Skipped: {len(skipped)} (no signals)")

    if scored:
        print(f"\nTOP RESULTS (by risk):")
        print(f"{'─'*60}")

        # Sort by score ascending (most risky first)
        scored.sort(key=lambda x: x["score"])

        for r in scored[:10]:
            bar_len = int(r["score"] / 10)
            bar = "█" * bar_len + "░" * (10 - bar_len)
            print(f"{r['name'][:30]:30} {bar} {r['score']:5.1f} [{r['risk_level'].upper()}]")
            print(f"  Signals: {r['signals']} | Confidence: {r['confidence']:.2f}")

    # Final database stats
    stats = await get_database_stats()
    print(f"\n{'─'*60}")
    print(f"Database summary:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Businesses scored:  {stats['businesses_scored']}")

    return scored

if __name__ == "__main__":
    results = asyncio.run(run_scorer())
    print(f"\nDone. {len(results)} businesses scored.")