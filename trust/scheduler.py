"""
Trust Layer Scheduler
Runs collectors and scorer automatically on a schedule.
Designed to run in the background while you do other things.

Schedule:
- GDELT collector: every 6 hours (news moves fast)
- Scorer: after every collector run
- Stats report: every 24 hours

Run with:
    python -m trust.scheduler
"""

import asyncio
import time
from datetime import datetime

def log(msg: str):
    """Timestamped log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

async def run_gdelt():
    """Run GDELT collector."""
    try:
        log("Starting GDELT collector...")
        from trust.collectors.gdelt import run_collector
        count = await run_collector(max_articles=50)
        log(f"GDELT complete — {count} articles processed")
        return count
    except Exception as e:
        log(f"GDELT failed: {e}")
        return 0

async def run_scorer():
    """Run trust scorer."""
    try:
        log("Running trust scorer...")
        from trust.scorer import run_scorer
        results = await run_scorer()
        log(f"Scorer complete — {len(results)} businesses scored")
        return len(results)
    except Exception as e:
        log(f"Scorer failed: {e}")
        return 0

async def run_worldbank():
    """Run World Bank collector."""
    try:
        log("Starting World Bank collector...")
        from trust.collectors.worldbank import run_collector
        count = await run_collector()
        log(f"World Bank complete — {count} data points collected")
        return count
    except Exception as e:
        log(f"World Bank failed: {e}")
        return 0

async def print_stats():
    """Print database statistics."""
    try:
        from trust.database import get_database_stats
        stats = await get_database_stats()
        log(f"DATABASE STATS:")
        log(f"  Businesses tracked: {stats['businesses_tracked']}")
        log(f"  Signals collected:  {stats['signals_collected']}")
        log(f"  Businesses scored:  {stats['businesses_scored']}")
        log(f"  Negative signals:   {stats['negative_signals']}")
    except Exception as e:
        log(f"Stats failed: {e}")

async def run_cycle():
    """Run one full collection and scoring cycle."""
    log("="*50)
    log("TRUST LAYER — Starting Collection Cycle")
    log("="*50)

    # Collect from all sources
    await run_gdelt()
    await run_worldbank()

    # Score
    await run_scorer()

    # Stats
    await print_stats()

    log("Cycle complete.")

async def run_scheduler(
    collection_interval_hours: int = 12,
    run_immediately: bool = True
):
    """
    Main scheduler loop.
    Runs collection cycles on a fixed interval.
    """
    log("="*50)
    log("TRUST LAYER SCHEDULER STARTED")
    log(f"Collection interval: every {collection_interval_hours} hours")
    log("Press Ctrl+C to stop")
    log("="*50)

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            log(f"Cycle #{cycle_count} starting...")

            await run_cycle()

            next_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log(f"Next cycle in {collection_interval_hours} hours")
            log(f"Sleeping until next run...")

            # Sleep for interval
            await asyncio.sleep(collection_interval_hours * 3600)

    except KeyboardInterrupt:
        log("Scheduler stopped by user.")
        from trust.database import close
        await close()

if __name__ == "__main__":
    asyncio.run(run_scheduler(
        collection_interval_hours=12,
        run_immediately=True
    ))