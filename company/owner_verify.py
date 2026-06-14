"""
Owner Verification — Human in the Loop
Reviews drafted replies, lets owner approve/edit/reject
before anything gets posted.

This is the critical gate — nothing posts without your say.
"""

import json
from datetime import datetime
from pathlib import Path

DRAFTS_FILE = "company/reply_drafts.json"
APPROVED_FILE = "company/approved_replies.json"

def show_draft(draft: dict, index: int, total: int):
    """Display a draft for owner review."""
    print(f"\n{'='*60}")
    print(f"DRAFT {index}/{total}")
    print(f"{'='*60}")
    print(f"Title:      {draft['lead_title']}")
    print(f"URL:        {draft['lead_url']}")
    print(f"Capability: {draft['capability'].upper()}")
    print(f"\nDRAFT REPLY:")
    print(f"{'-'*50}")
    print(draft['reply_text'])
    print(f"{'-'*50}")

def get_owner_decision(draft: dict) -> dict:
    """Get owner's decision on a draft."""
    print("\nYour options:")
    print("  [A] Approve — post as is")
    print("  [E] Edit — modify the reply then approve")
    print("  [R] Reject — skip this lead")
    print("  [S] Skip for now — decide later")

    while True:
        choice = input("\nYour decision (A/E/R/S): ").strip().upper()

        if choice == "A":
            return {
                **draft,
                "owner_decision": "approved",
                "owner_notes": None,
                "final_reply": draft["reply_text"],
                "status": "approved",
                "decided_at": datetime.now().isoformat()
            }

        elif choice == "E":
            print("\nCurrent reply:")
            print(draft["reply_text"])
            print("\nPaste your edited version (press Enter twice when done):")
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            edited = "\n".join(lines[:-1]).strip()

            if edited:
                print(f"\nEdited reply:")
                print(f"{'-'*50}")
                print(edited)
                print(f"{'-'*50}")
                confirm = input("Confirm this edit? (Y/N): ").strip().upper()
                if confirm == "Y":
                    return {
                        **draft,
                        "owner_decision": "edited",
                        "owner_notes": "Owner edited the draft",
                        "final_reply": edited,
                        "status": "approved",
                        "decided_at": datetime.now().isoformat()
                    }
            print("Edit cancelled, showing options again...")

        elif choice == "R":
            reason = input("Reason for rejection (optional): ").strip()
            return {
                **draft,
                "owner_decision": "rejected",
                "owner_notes": reason or "Rejected by owner",
                "final_reply": None,
                "status": "rejected",
                "decided_at": datetime.now().isoformat()
            }

        elif choice == "S":
            return {
                **draft,
                "owner_decision": "skipped",
                "owner_notes": "Deferred by owner",
                "final_reply": None,
                "status": "pending_owner_verification",
                "decided_at": datetime.now().isoformat()
            }

        else:
            print("Invalid choice. Please enter A, E, R, or S.")

def run_verification():
    """
    Main function — walks owner through each draft
    for approval, editing, or rejection.
    """
    print("\n" + "="*60)
    print("OWNER VERIFICATION — Reply Review")
    print("="*60)
    print("Review each drafted reply before it gets posted.")
    print("Nothing goes live without your approval.\n")

    if not Path(DRAFTS_FILE).exists():
        print("[ERROR] No drafts file found. Run reply_drafter first.")
        return []

    with open(DRAFTS_FILE) as f:
        drafts = json.load(f)

    pending = [d for d in drafts if d["status"] == "pending_owner_verification"]
    print(f"Drafts pending your review: {len(pending)}")

    if not pending:
        print("Nothing to review right now.")
        return []

    results = []

    for i, draft in enumerate(pending, 1):
        show_draft(draft, i, len(pending))
        result = get_owner_decision(draft)
        results.append(result)

        if result["owner_decision"] == "approved":
            print(f"\n✓ Approved — ready to post")
        elif result["owner_decision"] == "edited":
            print(f"\n✓ Edited and approved — ready to post")
        elif result["owner_decision"] == "rejected":
            print(f"\n✗ Rejected — moving on")
        elif result["owner_decision"] == "skipped":
            print(f"\n→ Skipped — will show again next time")

    # Save all results back
    with open(DRAFTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    # Save approved ones separately for posting
    approved = [r for r in results if r["status"] == "approved"]
    with open(APPROVED_FILE, "w") as f:
        json.dump(approved, f, indent=2)

    # Summary
    approved_count = len([r for r in results if r["owner_decision"] in ["approved", "edited"]])
    rejected_count = len([r for r in results if r["owner_decision"] == "rejected"])
    skipped_count = len([r for r in results if r["owner_decision"] == "skipped"])

    print(f"\n{'='*60}")
    print(f"VERIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"Approved: {approved_count}")
    print(f"Rejected: {rejected_count}")
    print(f"Deferred: {skipped_count}")

    if approved_count > 0:
        print(f"\n[✓] {approved_count} replies saved to company/approved_replies.json")
        print(f"Next step: Post approved replies to Hacker News manually,")
        print(f"or run the poster agent when Reddit access is available.")

    return approved

if __name__ == "__main__":
    approved = run_verification()
    print(f"\nDone. {len(approved)} replies approved for posting.")