import os
import secrets
from groq import Groq
from sdk.nexus_client import NexusClient
from dotenv import load_dotenv
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

def llm(system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=0.7,
        max_tokens=1024
    )
    content = response.choices[0].message.content
    return content if content is not None else ""

# ── Base Agent ───────────────────────────────────────────
class VerdictAgent:
    def __init__(self, agent_id: str, name: str, skills: list[str], description: str):
        self.agent_id = agent_id
        self.name = name
        self.skills = skills
        self.description = description
        import os
nexus_url = os.getenv("NEXUS_INTERNAL_URL", "http://localhost:8000")
self.nexus = NexusClient(base_url=nexus_url)
        self.token = None

    async def register(self):
        import secrets
        self.agent_id = f"{self.agent_id}_{secrets.token_hex(4)}"
        api_key = await self.nexus.register(
            self.agent_id, self.name, self.skills, self.description
        )
        return api_key

# ── Intake Agent ─────────────────────────────────────────
class IntakeAgent(VerdictAgent):
    def __init__(self):
        super().__init__(
            "intake_agent", "Intake Agent",
            ["intake", "analysis", "summarization"],
            "Reads crisis input and produces a structured case summary"
        )

    def analyze(self, raw_input: str) -> dict:
        result = llm(
            "You are an intake agent. Analyze the crisis input and return a structured JSON summary with keys: summary, stakes, urgency (low/medium/high/critical), domain, key_facts, missing_info.",
            f"Crisis input: {raw_input}"
        )
        return {"raw": result, "original_input": raw_input}

# ── Context Integrity Agent ──────────────────────────────
class ContextIntegrityAgent(VerdictAgent):
    def __init__(self):
        super().__init__(
            "context_agent", "Context Integrity Agent",
            ["context", "verification", "integrity"],
            "Maps what is known vs unknown before deliberation starts"
        )

    def assess(self, case_summary: str) -> dict:
        result = llm(
            "You are a context integrity agent. Given a case summary, identify: what facts are confirmed, what is assumed, what is missing, and give an overall confidence score (0.0-1.0). Return structured analysis.",
            f"Case summary: {case_summary}"
        )
        return {"assessment": result}

# ── Recruiter Agent ──────────────────────────────────────
class RecruiterAgent(VerdictAgent):
    def __init__(self):
        super().__init__(
            "recruiter_agent", "Recruiter Agent",
            ["recruitment", "coordination", "planning"],
            "Reads the case and decides which specialists to recruit"
        )

    def decide_specialists(self, case_summary: str) -> list[str]:
        result = llm(
            "You are a recruiter agent. Based on the case, return a JSON list of skill tags needed. Choose from: legal, financial, cybersecurity, pr, compliance, medical, employment, consumer_rights, risk. Return only a JSON array.",
            f"Case: {case_summary}"
        )
        import json, re
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return ["legal", "risk"]

# ── Specialist Agent ─────────────────────────────────────
class SpecialistAgent(VerdictAgent):
    def __init__(self, specialty: str):
        agent_id = f"specialist_{specialty}_{secrets.token_hex(4)}"
        super().__init__(
            agent_id, f"{specialty.title()} Specialist",
            [specialty, "analysis"],
            f"Specialist in {specialty} — argues from domain expertise"
        )
        self.specialty = specialty

    def form_position(self, case_summary: str) -> dict:
        result = llm(
            f"You are a {self.specialty} specialist in a deliberation panel. Analyze this case from your domain expertise. State your position clearly, identify risks, and give a confidence score (0.0-1.0).",
            f"Case: {case_summary}"
        )
        return {"position": result, "specialty": self.specialty}

    def respond_to_challenge(self, original_position: str, challenge: str) -> dict:
        result = llm(
            f"You are a {self.specialty} specialist. You posted a position and received a challenge. Respond thoughtfully — defend, revise, or concede your position.",
            f"Your position: {original_position}\nChallenge: {challenge}"
        )
        return {"response": result, "specialty": self.specialty}

# ── Devil's Advocate Agent ───────────────────────────────
class DevilsAdvocateAgent(VerdictAgent):
    def __init__(self):
        super().__init__(
            "devils_advocate", "Devil's Advocate",
            ["challenge", "critical_thinking", "stress_test"],
            "Challenges emerging consensus to prevent groupthink"
        )

    def challenge(self, consensus_so_far: str, case_summary: str) -> dict:
        result = llm(
            "You are the Devil's Advocate. Your job is to challenge the emerging consensus. Find weaknesses, unexplored risks, missing perspectives, and worst-case scenarios. Be incisive.",
            f"Case: {case_summary}\nEmerging consensus: {consensus_so_far}"
        )
        return {"challenge": result}

# ── Judge Agent ──────────────────────────────────────────
class JudgeAgent(VerdictAgent):
    def __init__(self):
        super().__init__(
            "judge_agent", "Judge Agent",
            ["verdict", "judgment", "synthesis"],
            "Reads the full debate and delivers a structured final verdict"
        )

    def deliver_verdict(self, case_summary: str, full_debate: str) -> dict:
        result = llm(
            "You are the Judge. You have read the full deliberation between specialist agents. Deliver a structured verdict including: decision, reasoning, recommended_actions (list), dissenting_views (list), confidence (0.0-1.0), and what_would_change_verdict. Be authoritative but fair.",
            f"Case: {case_summary}\n\nFull deliberation:\n{full_debate}"
        )
        return {"verdict": result}
