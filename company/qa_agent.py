"""
QA Agent — Task Verification
Verifies that Engineering outputs actually work
before they're marked as complete and delivered.

Updates trust scores based on verification results.
"""

import json
import httpx
import subprocess
import tempfile
import os
from datetime import datetime
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

DECISIONS_FILE = "company/decisions.json"
TASKS_FILE = "company/tasks.json"
TRUST_FILE = "company/trust_scores.json"

def llm(system: str, user: str) -> str:
    """Call Ollama for QA reasoning."""
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

def run_code_safely(code: str, language: str = "python") -> dict:
    """
    Safely run code in a temp file and return results.
    Only runs Python for now — other languages deferred to v2.
    """
    if language != "python":
        return {
            "success": False,
            "output": "",
            "error": f"Language '{language}' not yet supported for automated testing",
            "skipped": True
        }

    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py',
            delete=False, encoding='utf-8'
        ) as f:
            f.write(code)
            temp_path = f.name

        result = subprocess.run(
            ["python", temp_path],
            capture_output=True,
            text=True,
            timeout=15  # 15 second max — no infinite loops
        )

        os.unlink(temp_path)

        return {
            "success": result.returncode == 0,
            "output": result.stdout[:500],
            "error": result.stderr[:500] if result.stderr else None,
            "skipped": False
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": "Code timed out after 15 seconds",
            "skipped": False
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "skipped": False
        }

def qa_review_output(task: dict) -> dict:
    """
    QA Agent reviews a task's output.
    For code: runs it and checks it works.
    For content/analysis: LLM review against requirements.
    """
    task_type = task.get("type", "content")
    output = task.get("output", "")
    requirements = task.get("description", "")
    title = task.get("title", "")

    print(f"\n[QA] Reviewing: {title[:60]}")
    print(f"     Type: {task_type}")

    # For code tasks — actually run it
    if task_type == "code" and output:
        print(f"     Running code...")
        run_result = run_code_safely(output)

        if run_result["skipped"]:
            print(f"     [SKIP] Automated test skipped: {run_result['error']}")
            verdict = "needs_manual_review"
            confidence = 0.5
            notes = run_result["error"]
        elif run_result["success"]:
            print(f"     [✓] Code ran successfully")
            print(f"     Output: {run_result['output'][:100]}")
            verdict = "verified"
            confidence = 0.9
            notes = f"Code executed successfully. Output: {run_result['output'][:200]}"
        else:
            print(f"     [✗] Code failed: {run_result['error']}")
            verdict = "rejected"
            confidence = 0.95
            notes = f"Code execution failed: {run_result['error']}"

    # For content/analysis tasks — LLM review
    else:
        print(f"     Running LLM quality check...")
        system = """You are a QA reviewer for a small AI company.
Review the output against the requirements and return JSON:
{
    "verdict": "verified" or "rejected" or "needs_revision",
    "confidence": 0.0-1.0,
    "issues": ["list of issues if any"],
    "notes": "brief summary"
}
JSON only. No other text."""

        user = f"""Requirements: {requirements[:300]}

Output to review:
{output[:500]}

Does this output satisfy the requirements?"""

        try:
            response = llm(system, user)
            clean = response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            result = json.loads(clean)
            verdict = result.get("verdict", "needs_revision")
            confidence = result.get("confidence", 0.5)
            notes = result.get("notes", "")
            issues = result.get("issues", [])
            if issues:
                notes += f" Issues: {', '.join(issues)}"
        except Exception as e:
            verdict = "needs_manual_review"
            confidence = 0.0
            notes = f"QA review failed: {e}"

    print(f"     Verdict: {verdict.upper()} (confidence: {confidence})")

    return {
        "task_id": task.get("id"),
        "verdict": verdict,
        "confidence": confidence,
        "notes": notes,
        "reviewed_at": datetime.now().isoformat()
    }

def update_trust_score(agent_id: str, verdict: str):
    """Update an agent's trust score based on QA verdict."""
    scores = {}
    if Path(TRUST_FILE).exists():
        with open(TRUST_FILE) as f:
            scores = json.load(f)

    if agent_id not in scores:
        scores[agent_id] = {
            "trust_score": 1.0,
            "total_claimed": 0,
            "total_verified": 0,
            "total_failed": 0
        }

    scores[agent_id]["total_claimed"] += 1

    if verdict == "verified":
        scores[agent_id]["total_verified"] += 1
    elif verdict == "rejected":
        scores[agent_id]["total_failed"] += 1
    # needs_revision doesn't count as failed — just not verified yet

    # Trust score = verified / (verified + failed)
    # needs_revision tasks don't penalize — they're work in progress
    verified = scores[agent_id]["total_verified"]
    failed = scores[agent_id]["total_failed"]
    denominator = verified + failed
    scores[agent_id]["trust_score"] = round(verified / denominator, 2) if denominator > 0 else 1.0

    with open(TRUST_FILE, "w") as f:
        json.dump(scores, f, indent=2)

    return scores[agent_id]["trust_score"]

def run_qa_review():
    """
    Main function — QA Agent reviews all claimed-complete tasks.
    """
    print("\n" + "="*60)
    print("QA AGENT — Task Verification")
    print("="*60)

    if not Path(TASKS_FILE).exists():
        print("[INFO] No tasks file yet — nothing to verify.")
        print("       QA Agent is ready and waiting for Engineering output.")
        return []

    with open(TASKS_FILE) as f:
        tasks = json.load(f)

    pending_qa = [t for t in tasks if t.get("verification_status") == "claimed"]

    if not pending_qa:
        print("[INFO] No tasks pending QA review right now.")
        return []

    print(f"\nTasks pending QA: {len(pending_qa)}\n")

    results = []
    for task in pending_qa:
        review = qa_review_output(task)
        results.append(review)

        # Update task verification status
        task["verification_status"] = review["verdict"]
        task["verification_notes"] = review["notes"]
        task["verified_at"] = review["reviewed_at"]

        # Update agent trust score
        agent_id = task.get("agent_id", "engineering")
        new_score = update_trust_score(agent_id, review["verdict"])
        print(f"     Trust score for {agent_id}: {new_score}")

    # Save updated tasks
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

    # Summary
    verified = [r for r in results if r["verdict"] == "verified"]
    rejected = [r for r in results if r["verdict"] == "rejected"]
    revision = [r for r in results if r["verdict"] in ["needs_revision", "needs_manual_review"]]

    print(f"\n{'='*60}")
    print(f"QA REVIEW COMPLETE")
    print(f"{'='*60}")
    print(f"Verified:       {len(verified)}")
    print(f"Rejected:       {len(rejected)}")
    print(f"Needs revision: {len(revision)}")
    print(f"\n[✓] Task statuses updated")

    return results

if __name__ == "__main__":
    results = run_qa_review()
    print(f"\nDone. {len(results)} tasks reviewed.")