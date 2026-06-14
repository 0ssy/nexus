"""
Operations Agent — Tracks money, resources, and company health.
Monitors revenue vs costs, flags issues, generates reports.
Enforces financial rules (spending tiers, reserve, dividend checks).

Uses Ollama for analysis and recommendations.
"""

import json
import httpx
from datetime import datetime, date, timedelta
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

FINANCIALS_FILE = "company/financials.json"
REVENUE_FILE = "company/revenue_transactions.json"
COSTS_FILE = "company/cost_transactions.json"
TRUST_FILE = "company/trust_scores.json"
TASKS_FILE = "company/tasks.json"
POSTED_LOG_FILE = "company/posted_log.json"

# Financial rules
SPENDING_TIERS = {
    "auto_small": 20.0,       # $0-$20: autonomous, quiet
    "auto_flagged": 100.0,    # $20-$100: autonomous, flagged
    "approval_required": float('inf')  # $100+: needs approval
}
OPERATING_RESERVE = 30.0      # minimum balance to keep
CONSECUTIVE_WEEKS_NEEDED = 4  # for dividend eligibility

def llm(system: str, user: str) -> str:
    """Call Ollama for operations analysis."""
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "stream": False
            },
            timeout=120.0
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        raise Exception(f"Ollama failed: {e}")

def load_json(filepath: str, default=None):
    """Load JSON file or return default."""
    if default is None:
        default = []
    if not Path(filepath).exists():
        return default
    with open(filepath) as f:
        return json.load(f)

def save_json(filepath: str, data):
    """Save data to JSON file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def get_financials() -> dict:
    """Load or initialize company financials."""
    default = {
        "cumulative_revenue_confirmed": 0.0,
        "cumulative_revenue_claimed": 0.0,
        "cumulative_costs": 0.0,
        "current_balance": 0.0,
        "operating_reserve": OPERATING_RESERVE,
        "dividends_paid": 0.0,
        "consecutive_profitable_weeks": 0,
        "weekly_nets": [],
        "last_updated": datetime.now().isoformat()
    }
    if not Path(FINANCIALS_FILE).exists():
        save_json(FINANCIALS_FILE, default)
        return default
    with open(FINANCIALS_FILE) as f:
        return json.load(f)

def calculate_financials() -> dict:
    """
    Recalculate company financials from transactions.
    Only confirmed revenue counts toward real balance.
    """
    revenue_txns = load_json(REVENUE_FILE)
    cost_txns = load_json(COSTS_FILE)

    confirmed_revenue = sum(
        t["amount"] for t in revenue_txns
        if t.get("status") == "confirmed"
    )
    claimed_revenue = sum(
        t["amount"] for t in revenue_txns
        if t.get("status") in ["pending", "confirmed"]
    )
    total_costs = sum(
        t["amount"] for t in cost_txns
        if t.get("status") in ["approved", "completed"]
    )

    balance = confirmed_revenue - total_costs
    profit = confirmed_revenue - total_costs

    return {
        "confirmed_revenue": round(confirmed_revenue, 2),
        "claimed_revenue": round(claimed_revenue, 2),
        "total_costs": round(total_costs, 2),
        "current_balance": round(balance, 2),
        "profit": round(profit, 2),
        "revenue_gap": round(claimed_revenue - confirmed_revenue, 2),
        "above_reserve": round(balance - OPERATING_RESERVE, 2)
    }

def check_spending_tier(amount: float) -> dict:
    """
    Check which spending tier an amount falls into.
    Returns tier info and whether approval is needed.
    """
    if amount <= SPENDING_TIERS["auto_small"]:
        return {
            "tier": "auto_small",
            "needs_approval": False,
            "needs_flag": False,
            "message": f"${amount} — autonomous, no approval needed"
        }
    elif amount <= SPENDING_TIERS["auto_flagged"]:
        return {
            "tier": "auto_flagged",
            "needs_approval": False,
            "needs_flag": True,
            "message": f"${amount} — autonomous but flagged for visibility"
        }
    else:
        return {
            "tier": "approval_required",
            "needs_approval": True,
            "needs_flag": True,
            "message": f"${amount} — REQUIRES OWNER APPROVAL"
        }

def check_dividend_eligibility(financials: dict, weekly_nets: list) -> dict:
    """
    Check if dividend conditions are met:
    - 4 consecutive profitable weeks
    - Rolling average also positive
    - Balance above reserve
    - Owner decides — never auto-triggers
    """
    if len(weekly_nets) < CONSECUTIVE_WEEKS_NEEDED:
        return {
            "eligible": False,
            "reason": f"Only {len(weekly_nets)} weeks of data, need {CONSECUTIVE_WEEKS_NEEDED}"
        }

    last_four = weekly_nets[-CONSECUTIVE_WEEKS_NEEDED:]
    all_positive = all(w > 0 for w in last_four)
    rolling_avg = sum(last_four) / len(last_four)
    above_reserve = financials["current_balance"] > OPERATING_RESERVE

    if all_positive and rolling_avg > 0 and above_reserve:
        surplus = financials["current_balance"] - OPERATING_RESERVE
        return {
            "eligible": True,
            "reason": "4 consecutive profitable weeks, positive rolling average, above reserve",
            "available_for_dividend": round(surplus, 2),
            "note": "Owner review required — dividends never auto-trigger"
        }
    else:
        reasons = []
        if not all_positive:
            reasons.append("not all 4 weeks profitable")
        if rolling_avg <= 0:
            reasons.append("rolling average negative")
        if not above_reserve:
            reasons.append(f"balance below ${OPERATING_RESERVE} reserve")
        return {
            "eligible": False,
            "reason": ", ".join(reasons)
        }

def generate_report(financials: dict, calcs: dict, dividend_check: dict) -> str:
    """Generate an operations report using Ollama."""
    system = """You are the Operations Agent for a small AI company.
Generate a concise operations report based on the financial data.
Be direct, practical, and flag any concerns clearly.
Keep it under 200 words."""

    user = f"""Current financials:
- Confirmed Revenue: ${calcs['confirmed_revenue']}
- Claimed Revenue: ${calcs['claimed_revenue']} (gap: ${calcs['revenue_gap']})
- Total Costs: ${calcs['total_costs']}
- Current Balance: ${calcs['current_balance']}
- Above Reserve: ${calcs['above_reserve']}
- Profit: ${calcs['profit']}

Dividend eligible: {dividend_check['eligible']}
Reason: {dividend_check['reason']}

Write a brief operations report with:
1. Current status (healthy/warning/critical)
2. Key metrics
3. One recommendation
4. Any flags or concerns"""

    try:
        return llm(system, user)
    except Exception as e:
        return f"Report generation failed: {e}"

def run_operations():
    """
    Main function — Operations Agent reviews company health,
    tracks financials, and generates a status report.
    """
    print("\n" + "="*60)
    print("OPERATIONS AGENT — Company Health Check")
    print("="*60)

    # Load financials
    financials = get_financials()
    calcs = calculate_financials()

    print(f"\n📊 FINANCIAL SNAPSHOT")
    print(f"{'─'*40}")
    print(f"Confirmed Revenue:  ${calcs['confirmed_revenue']}")
    print(f"Claimed Revenue:    ${calcs['claimed_revenue']}")
    print(f"  (Gap — unverified: ${calcs['revenue_gap']})")
    print(f"Total Costs:        ${calcs['total_costs']}")
    print(f"Current Balance:    ${calcs['current_balance']}")
    print(f"Operating Reserve:  ${OPERATING_RESERVE}")
    print(f"Above Reserve:      ${calcs['above_reserve']}")
    print(f"Net Profit:         ${calcs['profit']}")

    # Trust scores
    trust_scores = load_json(TRUST_FILE, default={})
    if isinstance(trust_scores, dict) and trust_scores:
        print(f"\n🎯 AGENT TRUST SCORES")
        print(f"{'─'*40}")
        for agent, data in trust_scores.items():
            score = data.get("trust_score", 1.0)
            claimed = data.get("total_claimed", 0)
            verified = data.get("total_verified", 0)
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            print(f"{agent:20} {bar} {score:.2f} ({verified}/{claimed} verified)")

    # Activity summary
    posted = load_json(POSTED_LOG_FILE)
    tasks = load_json(TASKS_FILE)
    print(f"\n📈 ACTIVITY SUMMARY")
    print(f"{'─'*40}")
    print(f"Replies posted:     {len(posted)}")
    print(f"Tasks completed:    {len([t for t in tasks if t.get('verification_status') == 'verified'])}")
    print(f"Tasks pending QA:   {len([t for t in tasks if t.get('verification_status') == 'claimed'])}")
    print(f"Tasks need revision:{len([t for t in tasks if t.get('verification_status') == 'needs_revision'])}")

    # Dividend check
    weekly_nets = financials.get("weekly_nets", [])
    dividend_check = check_dividend_eligibility(financials, weekly_nets)
    print(f"\n💰 DIVIDEND STATUS")
    print(f"{'─'*40}")
    print(f"Eligible: {dividend_check['eligible']}")
    print(f"Reason: {dividend_check['reason']}")
    if dividend_check.get("available_for_dividend"):
        print(f"Available: ${dividend_check['available_for_dividend']}")
        print(f"Note: {dividend_check.get('note')}")

    # Spending tier reference
    print(f"\n⚖️  SPENDING TIERS")
    print(f"{'─'*40}")
    print(f"$0-$20:   Autonomous (quiet)")
    print(f"$20-$100: Autonomous (flagged)")
    print(f"$100+:    Requires your approval")

    # Generate LLM report
    print(f"\n📝 OPERATIONS REPORT")
    print(f"{'─'*40}")
    report = generate_report(financials, calcs, dividend_check)
    print(report)

    # Save updated financials
    financials.update({
        "cumulative_revenue_confirmed": calcs["confirmed_revenue"],
        "cumulative_revenue_claimed": calcs["claimed_revenue"],
        "cumulative_costs": calcs["total_costs"],
        "current_balance": calcs["current_balance"],
        "last_updated": datetime.now().isoformat()
    })
    save_json(FINANCIALS_FILE, financials)

    print(f"\n{'='*60}")
    print(f"[✓] Financials saved to company/financials.json")

    return calcs

if __name__ == "__main__":
    calcs = run_operations()
    print(f"\nDone.")