"""
Reply Drafter — Marketing Agent Phase 2
Takes CEO-approved leads and drafts personalized replies
for owner verification before posting.

Uses Ollama (local, free) for drafting.
All replies go through owner verification — nothing posts automatically.
"""

import json
import httpx
from datetime import datetime
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

DECISIONS_FILE = "company/decisions.json"
DRAFTS_FILE = "company/reply_drafts.json"

COMPANY_VOICE = """
You are a helpful, knowledgeable assistant representing a small AI advisory company.

TONE RULES:
- Sound like a real, helpful person — not a bot or corporate entity
- Be specific and reference their actual situation — never generic
- Be concise — HN replies should be 3-5 sentences max
- Lead with value — give something useful immediately, don't just pitch
- Never say "we are an AI company" or mention AI agents
- Never be pushy or salesy — offer help genuinely
- End with a soft open door — invite them to share more or reach out
- Sound like someone who has relevant experience, not someone selling a service
"""

CAPABILITY_PROMPTS = {
    "engineering": """
You can help with: building tools, writing scripts, solving technical problems,
API integrations, automation, small SaaS features, debugging.
Lead with a specific technical insight about their problem.
""",
    "marketing": """
You can help with: go-to-market strategy, content creation, positioning,
campaign planning, SEO, copywriting, growth tactics.
Lead with a specific marketing insight about their situation.
""",
    "operations": """
You can help with: process optimization, cost/revenue analysis,
workflow design, forecasting, resource allocation.
Lead with a specific operational insight about their problem.
""",
    "verdict": """
You can help with: breaking down complex decisions from multiple angles,
identifying risks they might have missed, providing structured analysis
before they take a costly or irreversible action.
Lead with acknowledging the difficulty of their decision.
"""
}

def llm(system: str, user: str) -> str:
    """Call Ollama for reply drafting."""
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

def draft_reply(decision: dict) -> dict:
    """Draft a personalized reply for a single approved lead."""
    capability = decision.get("capability", "verdict")
    capability_context = CAPABILITY_PROMPTS.get(capability, CAPABILITY_PROMPTS["verdict"])

    system = f"""{COMPANY_VOICE}

Your capability for this reply:
{capability_context}

Write a reply that:
1. References their specific situation (use details from their post)
2. Gives one concrete, immediately useful insight
3. Naturally mentions you could help further if they're interested
4. Stays under 100 words
5. Sounds human and genuine

Return only the reply text. No subject line, no preamble, no explanation."""

    user = f"""Write a reply to this Hacker News post:

Title: {decision['lead_title']}
What we can offer: {decision['what_we_offer']}
Key angle to hit: {decision['reply_angle']}

Write the reply now:"""

    try:
        reply_text = llm(system, user)
        return {
            "lead_id": decision["lead_id"],
            "lead_title": decision["lead_title"],
            "lead_url": decision["lead_url"],
            "capability": capability,
            "reply_text": reply_text.strip(),
            "drafted_at": datetime.now().isoformat(),
            "status": "pending_owner_verification",
            "owner_decision": None,
            "owner_notes": None,
            "posted_at": None
        }
    except Exception as e:
        return {
            "lead_id": decision["lead_id"],
            "lead_title": decision["lead_title"],
            "lead_url": decision["lead_url"],
            "capability": capability,
            "reply_text": None,
            "error": str(e),
            "drafted_at": datetime.now().isoformat(),
            "status": "draft_failed"
        }

def run_reply_drafter():
    """
    Main function — drafts replies for all CEO-approved leads
    and queues them for owner verification.
    """
    print("\n" + "="*60)
    print("REPLY DRAFTER — Marketing Agent Phase 2")
    print("="*60)

    # Load decisions
    if not Path(DECISIONS_FILE).exists():
        print("[ERROR] No decisions file found. Run ceo_agent first.")
        return []

    with open(DECISIONS_FILE) as f:
        decisions = json.load(f)

    # Only draft for approved leads that don't need VERDICT first
    to_draft = [
        d for d in decisions
        if d["status"] == "pending_reply_draft"
    ]

    needs_verdict = [
        d for d in decisions
        if d["status"] == "pending_verdict"
    ]

    print(f"\nLeads approved for drafting: {len(to_draft)}")
    if needs_verdict:
        print(f"Leads pending VERDICT review: {len(needs_verdict)} (skipping for now)")
    print()

    drafts = []

    for i, decision in enumerate(to_draft, 1):
        print(f"[{i}/{len(to_draft)}] Drafting reply for:")
        print(f"    {decision['lead_title'][:70]}")
        print(f"    Capability: {decision['capability'].upper()}")

        draft = draft_reply(decision)

        if draft["status"] == "pending_owner_verification":
            print(f"\n    DRAFT REPLY:")
            print(f"    {'-'*50}")
            # Indent each line of the reply
            for line in draft["reply_text"].split("\n"):
                print(f"    {line}")
            print(f"    {'-'*50}")
            print(f"    Status: Awaiting your verification")
        else:
            print(f"    [ERROR] Draft failed: {draft.get('error')}")

        drafts.append(draft)
        print()

    # Save drafts
    with open(DRAFTS_FILE, "w") as f:
        json.dump(drafts, f, indent=2)

    # Summary
    successful = [d for d in drafts if d["status"] == "pending_owner_verification"]
    failed = [d for d in drafts if d["status"] == "draft_failed"]

    print("="*60)
    print("REPLY DRAFTER COMPLETE")
    print("="*60)
    print(f"Drafted: {len(successful)}")
    print(f"Failed:  {len(failed)}")
    print(f"\n[✓] Drafts saved to company/reply_drafts.json")
    print(f"\nNext step: Review drafts and approve/edit before posting.")

    return drafts

if __name__ == "__main__":
    drafts = run_reply_drafter()
    print(f"\nDone. {len([d for d in drafts if d['status'] == 'pending_owner_verification'])} replies ready for your review.")