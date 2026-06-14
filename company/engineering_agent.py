"""
Engineering Agent — Builds things for clients
Takes approved leads routed to engineering capability
and builds what's needed: scripts, tools, small utilities.

All output goes through QA Agent before delivery.
Uses Ollama (local, free) for code generation.
"""

import json
import httpx
from datetime import datetime
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

DECISIONS_FILE = "company/decisions.json"
TASKS_FILE = "company/tasks.json"
TRUST_FILE = "company/trust_scores.json"

def llm(system: str, user: str) -> str:
    """Call Ollama for code generation."""
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
            timeout=180.0
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        raise Exception(f"Ollama failed: {e}")

def get_trust_score(agent_id: str) -> float:
    """Get current trust score for this agent."""
    if not Path(TRUST_FILE).exists():
        return 1.0
    with open(TRUST_FILE) as f:
        scores = json.load(f)
    return scores.get(agent_id, {}).get("trust_score", 1.0)

def analyze_request(lead: dict) -> dict:
    """
    Engineering Agent analyzes what needs to be built
    based on the lead details.
    """
    system = """You are a senior software engineer at a small AI company.
Analyze a client's request and define what needs to be built.

Return JSON only:
{
    "task_title": "short title of what to build",
    "task_type": "code" or "analysis" or "documentation",
    "language": "python" or "javascript" or "other",
    "description": "clear description of what to build",
    "complexity": "simple" or "medium" or "complex",
    "deliverable": "what the client will receive",
    "can_build": true or false,
    "reason": "why we can or cannot build this"
}
JSON only. No other text."""

    user = f"""Client request from Hacker News:

Title: {lead.get('lead_title', '')}
What we offered: {lead.get('what_we_offer', '')}
Reply angle: {lead.get('reply_angle', '')}

What should we build for this client?"""

    try:
        response = llm(system, user)
        clean = response.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        return json.loads(clean)
    except Exception as e:
        return {
            "task_title": "Analysis failed",
            "task_type": "analysis",
            "language": "python",
            "description": lead.get('lead_title', ''),
            "complexity": "simple",
            "deliverable": "Analysis report",
            "can_build": False,
            "reason": f"Analysis error: {e}"
        }

def build_solution(analysis: dict, lead: dict) -> str:
    """
    Engineering Agent builds the solution.
    Returns the code/content as a string.
    """
    system = f"""You are a senior software engineer.
Build a clean, working solution for the client's request.

Rules:
- Write complete, runnable code (not pseudocode)
- Include comments explaining what each part does
- Keep it simple and practical
- For Python: include example usage at the bottom
- Do not include explanations outside the code
- Return ONLY the code, nothing else"""

    user = f"""Build this for a client:

Task: {analysis['task_title']}
Description: {analysis['description']}
Language: {analysis['language']}
Deliverable: {analysis['deliverable']}

Client context: {lead.get('lead_title', '')}

Write the complete solution now:"""

    return llm(system, user)

def run_engineering():
    """
    Main function — Engineering Agent processes leads
    routed to engineering capability.
    """
    print("\n" + "="*60)
    print("ENGINEERING AGENT — Building Solutions")
    print("="*60)

    # Check trust score
    trust = get_trust_score("engineering")
    print(f"\nCurrent trust score: {trust}")
    if trust < 0.5:
        print("[WARNING] Trust score below 0.5 — routing complex tasks to owner review")

    # Load decisions
    if not Path(DECISIONS_FILE).exists():
        print("[INFO] No decisions file. Run ceo_agent first.")
        return []

    with open(DECISIONS_FILE) as f:
        decisions = json.load(f)

    # Only handle engineering leads
    engineering_leads = [
        d for d in decisions
        if d.get("capability") == "engineering"
        and d.get("status") == "pending_reply_draft"
        and d.get("ceo_decision") == "pursue"
    ]

    if not engineering_leads:
        print("[INFO] No engineering leads to work on right now.")
        return []

    print(f"\nEngineering leads: {len(engineering_leads)}\n")

    # Load existing tasks
    tasks = []
    if Path(TASKS_FILE).exists():
        with open(TASKS_FILE) as f:
            tasks = json.load(f)

    new_tasks = []

    for i, lead in enumerate(engineering_leads, 1):
        print(f"[{i}/{len(engineering_leads)}] Processing:")
        print(f"    {lead['lead_title'][:60]}")

        # Analyze what to build
        print(f"    Analyzing request...")
        analysis = analyze_request(lead)

        if not analysis.get("can_build"):
            print(f"    [SKIP] Cannot build: {analysis.get('reason')}")
            continue

        print(f"    Task: {analysis['task_title']}")
        print(f"    Type: {analysis['task_type']} | Complexity: {analysis['complexity']}")

        # Skip complex tasks if trust score is low
        if analysis["complexity"] == "complex" and trust < 0.7:
            print(f"    [SKIP] Complex task skipped — trust score too low ({trust})")
            print(f"           Routing to owner for manual handling")
            task = {
                "id": f"task_{lead['lead_id']}",
                "agent_id": "engineering",
                "lead_id": lead["lead_id"],
                "title": analysis["task_title"],
                "description": analysis["description"],
                "type": analysis["task_type"],
                "language": analysis.get("language", "python"),
                "complexity": analysis["complexity"],
                "deliverable": analysis["deliverable"],
                "output": None,
                "verification_status": "needs_manual_review",
                "verification_notes": "Complex task — low trust score, needs owner review",
                "status": "pending_owner_review",
                "created_at": datetime.now().isoformat()
            }
            new_tasks.append(task)
            continue

        # Build the solution
        print(f"    Building solution (this may take a minute)...")
        try:
            output = build_solution(analysis, lead)
            print(f"    [✓] Solution built ({len(output)} chars)")

            task = {
                "id": f"task_{lead['lead_id']}",
                "agent_id": "engineering",
                "lead_id": lead["lead_id"],
                "title": analysis["task_title"],
                "description": analysis["description"],
                "type": analysis["task_type"],
                "language": analysis.get("language", "python"),
                "complexity": analysis["complexity"],
                "deliverable": analysis["deliverable"],
                "output": output,
                "verification_status": "claimed",
                "verification_notes": None,
                "status": "pending_qa",
                "created_at": datetime.now().isoformat()
            }
            new_tasks.append(task)
            print(f"    → Sent to QA Agent for verification")

        except Exception as e:
            print(f"    [ERROR] Build failed: {e}")
            task = {
                "id": f"task_{lead['lead_id']}",
                "agent_id": "engineering",
                "lead_id": lead["lead_id"],
                "title": analysis["task_title"],
                "description": analysis["description"],
                "type": analysis["task_type"],
                "language": analysis.get("language", "python"),
                "complexity": analysis["complexity"],
                "deliverable": analysis["deliverable"],
                "output": None,
                "verification_status": "failed",
                "verification_notes": str(e),
                "status": "failed",
                "created_at": datetime.now().isoformat()
            }
            new_tasks.append(task)

        print()

    # Save tasks
    tasks.extend(new_tasks)
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

    # Summary
    built = [t for t in new_tasks if t["verification_status"] == "claimed"]
    skipped = [t for t in new_tasks if t["status"] == "pending_owner_review"]
    failed = [t for t in new_tasks if t["status"] == "failed"]

    print(f"{'='*60}")
    print(f"ENGINEERING COMPLETE")
    print(f"{'='*60}")
    print(f"Built (pending QA): {len(built)}")
    print(f"Skipped (owner review): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    if built:
        print(f"\n[✓] {len(built)} tasks sent to QA Agent")
        print("    Run: python -m company.qa_agent")

    return new_tasks

if __name__ == "__main__":
    tasks = run_engineering()
    print(f"\nDone. {len(tasks)} tasks processed.")