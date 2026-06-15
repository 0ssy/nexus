"""
Company Runner — Full Cycle
Runs the entire AI Company loop in order:

1. Marketing Agent  → finds leads on HN
2. CEO Agent        → reviews leads, decides pursue/skip
3. Reply Drafter    → writes personalized replies
4. Owner Verify     → YOU approve/edit/reject (interactive)
5. HN Poster        → posts approved replies
6. Engineering      → builds solutions for engineering leads
7. QA Agent         → verifies engineering output
8. Operations       → reports company health

Run this once a day (or whenever you want a cycle).
"""

import asyncio
import sys
from datetime import datetime

def header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def step(n: int, total: int, name: str):
    print(f"\n[Step {n}/{total}] {name}")
    print(f"{'─'*40}")

async def run_full_cycle():
    start_time = datetime.now()

    print("\n" + "="*60)
    print("  AI COMPANY — FULL CYCLE")
    print(f"  Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    total_steps = 8

    # ── Step 1: Marketing Agent ──────────────────────────────
    step(1, total_steps, "Marketing Agent — Finding Leads")
    try:
        from company.marketing_agent import find_leads
        leads = find_leads()
        print(f"\n✓ Found {len(leads)} leads")
    except Exception as e:
        print(f"✗ Marketing Agent failed: {e}")
        leads = []

    if not leads:
        print("\n[!] No leads found — stopping cycle early.")
        print("    Try again later or check HN for activity.")
        return

    # ── Step 2: CEO Agent ────────────────────────────────────
    step(2, total_steps, "CEO Agent — Reviewing Leads")
    try:
        from company.ceo_agent import run_ceo_review
        pursued = run_ceo_review()
        print(f"\n✓ CEO approved {len(pursued)} leads")
    except Exception as e:
        print(f"✗ CEO Agent failed: {e}")
        pursued = []

    if not pursued:
        print("\n[!] No leads approved — stopping cycle early.")
        print("    CEO found nothing worth pursuing this run.")
        return

    # ── Step 3: Reply Drafter ────────────────────────────────
    step(3, total_steps, "Reply Drafter — Writing Replies")
    try:
        from company.reply_drafter import run_reply_drafter
        drafts = run_reply_drafter()
        ready = [d for d in drafts if d["status"] == "pending_owner_verification"]
        print(f"\n✓ {len(ready)} replies drafted and ready for review")
    except Exception as e:
        print(f"✗ Reply Drafter failed: {e}")
        drafts = []

    # ── Step 4: Owner Verification ───────────────────────────
    step(4, total_steps, "Owner Verification — YOUR TURN")
    print("\n[!] This step requires your input.")
    print("    Review each reply and approve, edit, or reject it.\n")

    try:
        from company.owner_verify import run_verification
        approved = run_verification()
        print(f"\n✓ {len(approved)} replies approved")
    except Exception as e:
        print(f"✗ Verification failed: {e}")
        approved = []

    # ── Step 5: HN Poster ────────────────────────────────────
    step(5, total_steps, "HN Poster — Posting Approved Replies")
    if not approved:
        print("[SKIP] No approved replies to post.")
        posted = []
    else:
        try:
            from company.hn_poster import run_hn_poster
            posted = await run_hn_poster()
            print(f"\n✓ {len(posted)} replies posted to Hacker News")
        except Exception as e:
            print(f"✗ HN Poster failed: {e}")
            posted = []

    # ── Step 6: Engineering Agent ────────────────────────────
    step(6, total_steps, "Engineering Agent — Building Solutions")
    try:
        from company.engineering_agent import run_engineering
        tasks = run_engineering()
        built = [t for t in tasks if t.get("verification_status") == "claimed"]
        print(f"\n✓ {len(built)} solutions built, sent to QA")
    except Exception as e:
        print(f"✗ Engineering Agent failed: {e}")
        tasks = []

    # ── Step 7: QA Agent ─────────────────────────────────────
    step(7, total_steps, "QA Agent — Verifying Output")
    verified = []
    try:
        from company.qa_agent import run_qa_review
        qa_results = run_qa_review()
        verified = [r for r in qa_results if r.get("verdict") == "verified"]
        print(f"\n✓ {len(verified)}/{len(qa_results)} tasks verified")
    except Exception as e:
        print(f"✗ QA Agent failed: {e}")
        qa_results = []

    # ── Step 8: Operations Agent ─────────────────────────────
    step(8, total_steps, "Operations Agent — Company Health Check")
    try:
        from company.operations_agent import run_operations
        calcs = run_operations()
        print(f"\n✓ Operations report complete")
        print(f"  Balance: ${calcs['current_balance']} | Profit: ${calcs['profit']}")
    except Exception as e:
        print(f"✗ Operations Agent failed: {e}")

    # ── Cycle Summary ────────────────────────────────────────
    end_time = datetime.now()
    duration = (end_time - start_time).seconds

    print(f"\n{'='*60}")
    print(f"  CYCLE COMPLETE")
    print(f"{'='*60}")
    print(f"  Duration:     {duration}s")
    print(f"  Leads found:  {len(leads)}")
    print(f"  CEO approved: {len(pursued)}")
    print(f"  Replies sent: {len(posted) if 'posted' in dir() else 0}")
    print(f"  Tasks built:  {len(tasks) if 'tasks' in dir() else 0}")
    print(f"  QA verified:  {len(verified) if 'verified' in dir() else 0}")
    print(f"\n  Next run: whenever you're ready.")
    print(f"  Command:  python -m company.run_company")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(run_full_cycle())