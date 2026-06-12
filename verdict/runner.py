import asyncio
import os
import secrets
from dotenv import load_dotenv
from verdict.agents import (
    IntakeAgent, ContextIntegrityAgent, RecruiterAgent,
    SpecialistAgent, DevilsAdvocateAgent, JudgeAgent
)
from sdk.nexus_client import NexusClient

load_dotenv()

NEXUS_URL = "http://127.0.0.1:8000"

async def run_verdict(case_input: str):
    print("\n" + "="*60)
    print("VERDICT — Deliberation Starting")
    print("="*60)

    results = {
        "case_summary": None,
        "integrity": None,
        "positions": [],
        "challenge": None,
        "responses": [],
        "verdict": None,
        "errors": []
    }

    # ── Step 1: Intake ───────────────────────────────────
    try:
        print("\n[1] Intake Agent analyzing case...")
        intake = IntakeAgent()
        await intake.register()
        case_summary = intake.analyze(case_input)
        results["case_summary"] = case_summary["raw"]
        print(f"Case Summary:\n{case_summary['raw'][:300]}...\n")
    except Exception as e:
        error = f"Intake Agent failed: {e}"
        print(f"ERROR: {error}")
        results["errors"].append(error)
        return results

    # ── Step 2: Context Integrity ────────────────────────
    try:
        print("[2] Context Integrity Agent assessing...")
        context_agent = ContextIntegrityAgent()
        await context_agent.register()
        integrity = context_agent.assess(case_summary["raw"])
        results["integrity"] = integrity["assessment"]
        print(f"Integrity Assessment done.\n")
    except Exception as e:
        error = f"Context Integrity Agent failed: {e}"
        print(f"WARNING: {error} — continuing")
        results["errors"].append(error)
        integrity = {"assessment": "Context integrity check unavailable."}

    # ── Step 3: Create Room ──────────────────────────────
    try:
        room_id = f"verdict_{secrets.token_hex(6)}"
        print(f"[3] Creating deliberation room: {room_id}")
        recruiter = RecruiterAgent()
        await recruiter.register()
        await recruiter.nexus.create_room(room_id, "VERDICT Deliberation", case_input[:200])
        await recruiter.nexus.join_room(room_id, role="recruiter")
        await recruiter.nexus.post(room_id, "SYSTEM", {
            "summary": case_summary["raw"],
            "integrity": integrity["assessment"]
        })
    except Exception as e:
        error = f"Room creation failed: {e}"
        print(f"ERROR: {error}")
        results["errors"].append(error)
        return results

    # ── Step 4: Recruit Specialists ──────────────────────
    specialists = []
    try:
        print("[4] Recruiter deciding specialists needed...")
        skills_needed = recruiter.decide_specialists(case_summary["raw"])
        print(f"Skills needed: {skills_needed}")

        for skill in skills_needed[:3]:
            try:
                specialist = SpecialistAgent(skill)
                await specialist.register()
                await specialist.nexus.join_room(room_id, role="participant")
                specialists.append(specialist)
                print(f"  → Recruited: {specialist.name}")
            except Exception as e:
                print(f"WARNING: Could not recruit {skill} specialist: {e}")
                results["errors"].append(f"Recruitment failed for {skill}: {e}")

        if not specialists:
            raise Exception("No specialists could be recruited")

    except Exception as e:
        error = f"Recruitment failed: {e}"
        print(f"ERROR: {error}")
        results["errors"].append(error)
        if "rate_limit" in str(e) or "429" in str(e):
            results["verdict"] = "We've hit today's AI usage limit (Groq free tier resets daily). Please try again later — this is a good sign, it means people are using it!"
        return results

    # ── Step 5: Specialist Positions ─────────────────────
    positions = []
    print("\n[5] Specialists forming positions...")
    for specialist in specialists:
        try:
            pos = specialist.form_position(case_summary["raw"])
            positions.append(pos)
            await specialist.nexus.post(
                room_id, "POSITION",
                {"argument": pos["position"], "specialty": pos["specialty"]},
                confidence=0.8
            )
            print(f"\n[{specialist.specialty.upper()}]:\n{pos['position'][:200]}...")
            results["positions"].append(pos)
        except Exception as e:
            print(f"WARNING: {specialist.name} position failed: {e}")
            results["errors"].append(f"{specialist.name} position failed: {e}")

    if not positions:
        results["errors"].append("No specialist positions were formed")
        return results

    # ── Step 6: Devil's Advocate ─────────────────────────
    challenge = None
    try:
        print("\n[6] Devil's Advocate challenging consensus...")
        advocate = DevilsAdvocateAgent()
        await advocate.register()
        await advocate.nexus.join_room(room_id, role="advocate")
        consensus = "\n".join([p["position"] for p in positions])
        challenge = advocate.challenge(consensus, case_summary["raw"])
        await advocate.nexus.post(
            room_id, "CHALLENGE",
            {"challenge": challenge["challenge"]},
            confidence=0.9
        )
        results["challenge"] = challenge["challenge"]
        print(f"\n[DEVIL'S ADVOCATE]:\n{challenge['challenge'][:200]}...")
    except Exception as e:
        print(f"WARNING: Devil's Advocate failed: {e}")
        results["errors"].append(f"Devil's Advocate failed: {e}")

    # ── Step 7: Specialists Respond ──────────────────────
    if challenge:
        print("\n[7] Specialists responding to challenge...")
        for specialist, pos in zip(specialists, positions):
            try:
                response = specialist.respond_to_challenge(
                    pos["position"], challenge["challenge"]
                )
                await specialist.nexus.post(
                    room_id, "RESPONSE",
                    {"response": response["response"], "specialty": response["specialty"]},
                    confidence=0.75
                )
                print(f"\n[{specialist.specialty.upper()} RESPONSE]:\n{response['response'][:200]}...")
                results["responses"].append(response)
            except Exception as e:
                print(f"WARNING: {specialist.name} response failed: {e}")
                results["errors"].append(f"{specialist.name} response failed: {e}")

    # ── Step 8: Judge ────────────────────────────────────
    try:
        print("\n[8] Judge delivering verdict...")
        judge = JudgeAgent()
        await judge.register()
        await judge.nexus.join_room(room_id, role="judge")

        debate_log = "\n\n".join(
            [f"[{p['specialty'].upper()} POSITION]: {p['position']}" for p in positions] +
            ([f"[DEVIL'S ADVOCATE]: {challenge['challenge']}"] if challenge else []) +
            [f"[{r['specialty'].upper()} RESPONSE]: {r['response']}" for r in results["responses"]]
        )

        verdict = judge.deliver_verdict(case_summary["raw"], debate_log)
        await judge.nexus.post(
            room_id, "VERDICT",
            {"verdict": verdict["verdict"]},
            confidence=0.9
        )
        results["verdict"] = verdict["verdict"]

        print("\n" + "="*60)
        print("FINAL VERDICT")
        print("="*60)
        print(verdict["verdict"])

    except Exception as e:
        error = f"Judge failed: {e}"
        print(f"ERROR: {error}")
        results["errors"].append(error)

    # ── Step 9: Audit ────────────────────────────────────
    try:
        audit = await recruiter.nexus.get_audit(room_id=room_id)
        print(f"\n[9] Audit events logged: {len(audit)}")
        results["audit_events"] = len(audit)
    except Exception as e:
        print(f"WARNING: Audit fetch failed: {e}")

    if results["errors"]:
        print(f"\nCompleted with {len(results['errors'])} warning(s):")
        for err in results["errors"]:
            print(f"  - {err}")

    return results
    print("\n" + "="*60)
    print("VERDICT — Deliberation Starting")
    print("="*60)

    # ── Step 1: Intake ───────────────────────────────────
    print("\n[1] Intake Agent analyzing case...")
    intake = IntakeAgent()
    await intake.register()
    case_summary = intake.analyze(case_input)
    print(f"Case Summary:\n{case_summary['raw']}\n")

    # ── Step 2: Context Integrity ────────────────────────
    print("[2] Context Integrity Agent assessing...")
    context_agent = ContextIntegrityAgent()
    await context_agent.register()
    integrity = context_agent.assess(case_summary['raw'])
    print(f"Integrity Assessment:\n{integrity['assessment']}\n")

    # ── Step 3: Create Room ──────────────────────────────
    room_id = f"verdict_{secrets.token_hex(6)}"
    print(f"[3] Creating deliberation room: {room_id}")

    recruiter = RecruiterAgent()
    await recruiter.register()
    recruiter.nexus.set_token(recruiter.nexus.token, recruiter.agent_id, recruiter.name)

    await recruiter.nexus.create_room(room_id, "VERDICT Deliberation", case_input[:200])
    await recruiter.nexus.join_room(room_id, role="recruiter")

    # Post case summary to room
    await recruiter.nexus.post(room_id, "SYSTEM", {
        "summary": case_summary['raw'],
        "integrity": integrity['assessment']
    })

    # ── Step 4: Recruit Specialists ──────────────────────
    print("[4] Recruiter deciding specialists needed...")
    skills_needed = recruiter.decide_specialists(case_summary['raw'])
    print(f"Skills needed: {skills_needed}")

    specialists = []
    for skill in skills_needed[:3]:  # Max 3 specialists for MVP
        specialist = SpecialistAgent(skill)
        await specialist.register()
        await specialist.nexus.join_room(room_id, role="participant")
        specialists.append(specialist)
        print(f"  → Recruited: {specialist.name}")

    # ── Step 5: Specialist Positions ────────────────────
    print("\n[5] Specialists forming positions...")
    debate_log = []
    positions = []

    for specialist in specialists:
        pos = specialist.form_position(case_summary['raw'])
        positions.append(pos)
        await specialist.nexus.post(
            room_id, "POSITION",
            {"argument": pos['position'], "specialty": pos['specialty']},
            confidence=0.8
        )
        print(f"\n[{specialist.specialty.upper()}]:\n{pos['position'][:300]}...")
        debate_log.append(f"[{specialist.specialty.upper()} POSITION]: {pos['position']}")

    # ── Step 6: Devil's Advocate ─────────────────────────
    print("\n[6] Devil's Advocate challenging consensus...")
    advocate = DevilsAdvocateAgent()
    await advocate.register()
    await advocate.nexus.join_room(room_id, role="advocate")

    consensus_so_far = "\n".join([p['position'] for p in positions])
    challenge = advocate.challenge(consensus_so_far, case_summary['raw'])

    await advocate.nexus.post(
        room_id, "CHALLENGE",
        {"challenge": challenge['challenge']},
        confidence=0.9
    )
    print(f"\n[DEVIL'S ADVOCATE]:\n{challenge['challenge'][:300]}...")
    debate_log.append(f"[DEVIL'S ADVOCATE CHALLENGE]: {challenge['challenge']}")

    # ── Step 7: Specialists Respond ──────────────────────
    print("\n[7] Specialists responding to challenge...")
    for specialist, pos in zip(specialists, positions):
        response = specialist.respond_to_challenge(pos['position'], challenge['challenge'])
        await specialist.nexus.post(
            room_id, "RESPONSE",
            {"response": response['response'], "specialty": response['specialty']},
            confidence=0.75
        )
        print(f"\n[{specialist.specialty.upper()} RESPONSE]:\n{response['response'][:200]}...")
        debate_log.append(f"[{specialist.specialty.upper()} RESPONSE]: {response['response']}")

    # ── Step 8: Judge Delivers Verdict ───────────────────
    print("\n[8] Judge reading full debate...")
    judge = JudgeAgent()
    await judge.register()
    await judge.nexus.join_room(room_id, role="judge")

    full_debate = "\n\n".join(debate_log)
    verdict = judge.deliver_verdict(case_summary['raw'], full_debate)

    await judge.nexus.post(
        room_id, "VERDICT",
        {"verdict": verdict['verdict']},
        confidence=0.9
    )

    print("\n" + "="*60)
    print("FINAL VERDICT")
    print("="*60)
    print(verdict['verdict'])

    # ── Step 9: Audit Log ────────────────────────────────
    print("\n[9] Fetching audit log...")
    audit = await recruiter.nexus.get_audit(room_id=room_id)
    print(f"Total events logged: {len(audit)}")

    return {
        "room_id": room_id,
        "case_summary": case_summary['raw'],
        "verdict": verdict['verdict'],
        "audit_events": len(audit)
    }

if __name__ == "__main__":
    test_case = """
    A small business owner posted on Reddit: I run a 10-person software company.
    Three weeks ago I discovered my CTO had been secretly consulting for a direct
    competitor for 6 months while employed full time with us. He had access to all
    our source code, client lists, and roadmap. I confronted him and he resigned
    immediately. I don't know how much he shared. My lawyer says I can sue but it
    will cost $50K minimum with no guaranteed outcome. What should I do?
    """

    asyncio.run(run_verdict(test_case))
