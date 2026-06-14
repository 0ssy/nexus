"""
CEO Agent — Lead Reviewer
Reviews leads found by the Marketing Agent,
decides which ones to pursue, and routes them
for reply drafting.

Uses Ollama (local, free) for reasoning.
Trust scores and financial rules enforced.
"""

import json
import httpx
import asyncio
from datetime import datetime
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

LEADS_FILE = "company/leads.json"
DECISIONS_FILE = "company/decisions.json"

# Company capabilities — what we can actually help with
COMPANY_CAPABILITIES = """
ENGINEERING (we can build this):
- Custom scripts, automation tools, small software utilities
- Data processing pipelines, scrapers, API integrations
- Technical problem solving, debugging, code review
- Small SaaS tools, browser extensions, CLI tools

MARKETING (we can create this):
- Content strategy and written content (blog posts, social, email)
- Campaign planning and copywriting
- SEO analysis and recommendations
- Go-to-market strategy and positioning

OPERATIONS (we can analyze and track this):
- Business process analysis and optimization
- Cost/revenue forecasting and financial modeling
- Resource allocation recommendations
- Workflow design and efficiency improvements

VERDICT (we can deliberate on this):
- Complex business decisions needing multiple perspectives
- Contract disputes, HR issues, partner conflicts
- Risk assessment before escalation (legal, financial, HR)
- "Should I do X" decisions with real stakes
"""

# CEO decision rules
CEO_RULES = """
RULES FOR EVALUATING LEADS:
1. Pursue leads that match ANY of our four capabilities — Engineering, Marketing, Operations, or VERDICT
2. Prioritize leads with real stakes and genuine need — not curiosity or homework
3. Skip leads where the person already has a solution or is just sharing news
4. Skip job postings, hiring announcements, or spam
5. Skip leads completely outside our capabilities (e.g. medical, legal representation, hardware)
6. Prefer leads with active engagement (comments, upvotes)
7. Maximum 5 leads to pursue per run — quality over quantity
8. For ambiguous leads (could help but not sure), mark confidence below 0.7
"""
RULES_FOR_EVALUATING_LEADS = """
1. Only pursue leads where we can genuinely help — don't stretch capabilities
2. Prioritize leads with high stakes (legal, financial, HR) — these users need us most
3. Skip leads that are too vague, too personal, or outside our expertise
4. Skip leads that are job postings, hiring announcements, or spam
5. Skip leads where the person already has a clear solution
6. Prefer leads with active engagement (comments, upvotes) — means real interest
7. Be honest — if we can't help well, skip it
8. Maximum 5 leads to pursue per run — quality over quantity
"""

def llm(system: str, user: str) -> str:
    """Call Ollama for CEO reasoning."""
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
        raise Exception(f"Ollama failed: {e}") from e

def evaluate_lead(lead: dict) -> dict:
    """
    CEO Agent evaluates a single lead.
    Returns decision: pursue/skip + reasoning.
    """
    system = f"""You are the CEO of a small AI advisory company.
Your company helps people with:
{COMPANY_CAPABILITIES}

{CEO_RULES}

Respond in this exact JSON format:
{{
    "decision": "pursue" or "skip",
    "confidence": 0.0-1.0,
    "capability": "engineering" or "marketing" or "operations" or "verdict",
    "reasoning": "one sentence why",
    "what_we_offer": "one sentence on how we help (only if pursuing)",
    "reply_angle": "the key point our reply should make (only if pursuing)"
}}

Respond with JSON only. No other text."""

    user = f"""Evaluate this lead:

Title: {lead['title']}
Body: {lead['body'][:300] if lead['body'] else 'No body text'}
Platform: {lead.get('platform', 'hackernews')}
Points: {lead.get('points', 0)}
Comments: {lead.get('comments', 0)}
Our relevance score: {lead['score']}/10

Should we respond to this?"""

    try:
        response = llm(system, user)
        # Clean response — remove any markdown code blocks
        clean = response.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "decision": "skip",
            "confidence": 0.0,
            "reasoning": "CEO Agent failed to parse response",
            "what_we_offer": "",
            "reply_angle": ""
        }
    except Exception as e:
        return {
            "decision": "skip",
            "confidence": 0.0,
            "reasoning": f"CEO Agent error: {e}",
            "what_we_offer": "",
            "reply_angle": ""
        }

def run_ceo_review():
    """
    Main function — CEO reviews all pending leads
    and makes pursue/skip decisions.
    """
    print("\n" + "="*60)
    print("CEO AGENT — Lead Review Session")
    print("="*60)

    # Load leads
    if not Path(LEADS_FILE).exists():
        print("[ERROR] No leads file found. Run marketing_agent first.")
        return []

    with open(LEADS_FILE) as f:
        leads = json.load(f)

    pending = [l for l in leads if l.get("status") == "pending_ceo_review"]
    print(f"\nLeads to review: {len(pending)}")
    print(f"Reviewing top 10 by score...\n")

    # Review top 10 only — avoid burning too much time/compute
    to_review = sorted(pending, key=lambda x: x["score"], reverse=True)[:10]

    decisions = []
    pursue_count = 0
    max_pursue = 5  # CEO rule: max 5 per run

    for i, lead in enumerate(to_review, 1):
        print(f"[{i}/10] Evaluating: {lead['title'][:60]}...")

        if pursue_count >= max_pursue:
            decision_result = {
                "decision": "skip",
                "confidence": 1.0,
                "reasoning": "Max pursue limit reached for this run",
                "what_we_offer": "",
                "reply_angle": ""
            }
        else:
            decision_result = evaluate_lead(lead)

        decision = {
            "lead_id": lead["id"],
            "lead_title": lead["title"],
            "lead_url": lead["url"],
            "lead_score": lead["score"],
            "platform": lead.get("platform", "hackernews"),
            "ceo_decision": decision_result.get("decision", "skip"),
            "confidence": decision_result.get("confidence", 0.0),
            "capability": decision_result.get("capability", "verdict"),
            "reasoning": decision_result.get("reasoning", ""),
            "what_we_offer": decision_result.get("what_we_offer", ""),
            "reply_angle": decision_result.get("reply_angle", ""),
            "needs_verdict": decision_result.get("confidence", 0.0) < 0.7 and decision_result.get("decision") == "pursue",
            "decided_at": datetime.now().isoformat(),
            "status": "pending_verdict" if (decision_result.get("confidence", 0.0) < 0.7 and decision_result.get("decision") == "pursue") else ("pending_reply_draft" if decision_result.get("decision") == "pursue" else "skipped")
        }

        decisions.append(decision)

        if decision["ceo_decision"] == "pursue":
            pursue_count += 1
            capability = decision.get('capability', 'verdict').upper()
            needs_verdict = decision.get('needs_verdict', False)
            print(f"    ✓ PURSUE [{capability}] — {decision['reasoning']}")
            print(f"    Angle: {decision['reply_angle']}")
            if needs_verdict:
                print(f"    → Routing to VERDICT (confidence < 0.7)")
        else:
            print(f"    ✗ SKIP — {decision['reasoning']}")

        print()

    # Save decisions
    with open(DECISIONS_FILE, "w") as f:
        json.dump(decisions, f, indent=2)

    # Summary
    pursued = [d for d in decisions if d["ceo_decision"] == "pursue"]
    skipped = [d for d in decisions if d["ceo_decision"] == "skip"]

    print("="*60)
    print(f"CEO REVIEW COMPLETE")
    print("="*60)
    print(f"Reviewed: {len(decisions)}")
    print(f"Pursuing: {len(pursued)}")
    print(f"Skipped:  {len(skipped)}")
    print(f"\nLeads to pursue:")
    for d in pursued:
        print(f"  → {d['lead_title'][:70]}")
        print(f"    {d['lead_url']}")
    print(f"\n[✓] Decisions saved to company/decisions.json")

    return pursued

if __name__ == "__main__":
    pursued = run_ceo_review()
    print(f"\nDone. {len(pursued)} leads approved for reply drafting.")