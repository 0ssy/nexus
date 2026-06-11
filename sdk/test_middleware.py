"""
Test the NEXUS Middleware Adapter.
Simulates three existing agents passing their outputs
into NEXUS for consensus building.
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

from sdk.middleware import NexusMiddleware

# ── Simulate existing agent outputs ──────────────────────
# These represent outputs from ANY existing agent framework
# LangChain, CrewAI, raw OpenAI — doesn't matter
# Just pass the string output into NEXUS

CASE = """
A 50-person fintech startup is considering migrating their 
entire backend from AWS to Google Cloud. The migration would 
take 6 months, cost $400K, and require 3 senior engineers 
full time. Current AWS bill is $85K/month. Google Cloud 
estimates $55K/month after migration. The CTO wants to proceed.
The CFO is concerned about execution risk during a critical 
growth phase. What should they do?
"""

AGENT_OUTPUTS = [
    {
        "agent": "technical_analyst",
        "skills": ["technical", "cloud", "infrastructure"],
        "output": """
        From a technical perspective, the migration is feasible but risky.
        AWS to GCP migrations of this scale typically take 8-12 months, not 6.
        The $400K estimate is likely 30% low based on industry averages.
        Key risks: data transfer costs, staff retraining, potential downtime.
        However, the $30K/month savings ($360K/year) creates strong ROI after year one.
        Recommendation: Proceed with a phased migration over 12 months with a 
        parallel running period of at least 60 days before full cutover.
        """,
        "confidence": 0.8
    },
    {
        "agent": "financial_analyst",
        "skills": ["financial", "risk", "roi"],
        "output": """
        Financial analysis of the migration:
        Current AWS cost: $85K/month = $1.02M/year
        Projected GCP cost: $55K/month = $660K/year
        Annual savings: $360K
        Migration cost: $400K (likely $520K with overruns)
        Break-even: 17 months post-migration
        
        Critical concern: 3 senior engineers at full capacity for 6 months 
        represents $450K in opportunity cost if they could be building product.
        Total true cost: $970K. Break-even moves to 32 months.
        Recommendation: Delay migration until post Series B when engineering 
        capacity is less constrained.
        """,
        "confidence": 0.85
    },
    {
        "agent": "risk_analyst",
        "skills": ["risk", "compliance", "operations"],
        "output": """
        Risk assessment for AWS to GCP migration:
        
        HIGH RISKS:
        1. Migration during growth phase could cause service disruptions
        2. Customer data handling during transfer requires regulatory review
        3. Team burnout — engineers pulled from product development
        4. Vendor lock-in trading one dependency for another
        
        MEDIUM RISKS:
        1. Cost overruns are highly likely (industry average: 35% over budget)
        2. Timeline slippage could coincide with critical product launches
        
        LOW RISKS:
        1. Technical capability — GCP is enterprise-ready
        2. Support — both vendors offer enterprise SLAs
        
        Recommendation: If migration proceeds, require a rollback plan, 
        dedicated migration team separate from product engineers, and 
        board approval given the financial materiality.
        """,
        "confidence": 0.9
    }
]

async def main():
    print("\n" + "="*60)
    print("NEXUS MIDDLEWARE — Integration Test")
    print("="*60)
    print("\nSimulating 3 existing agents passing outputs to NEXUS...")
    print("No agent rewrites needed. Just plug in and collaborate.\n")

    nexus = NexusMiddleware()

    # Setup middleware
    print("[1] Setting up NEXUS middleware...")
    await nexus.setup(
        agent_id="test_middleware",
        skills=["orchestration", "coordination"],
        name="Test Middleware"
    )
    print("    Connected to NEXUS\n")

    # Run collaboration
    print("[2] Routing agent outputs through NEXUS...\n")
    result = await nexus.collaborate(
        agent_outputs=AGENT_OUTPUTS,
        case_context=CASE,
        room_name="Cloud Migration Decision"
    )

    # Print results
    print("="*60)
    print("NEXUS COLLABORATION RESULT")
    print("="*60)
    print(f"\nRoom ID: {result.room_id}")
    print(f"Agents Participated: {result.agents_participated}")
    print(f"Audit Events: {result.audit_events}")
    print(f"Loops Blocked: {result.loops_blocked}")
    print(f"Messages Filtered: {result.messages_filtered}")
    print(f"Tokens Saved: {result.tokens_saved}")
    print(f"Confidence: {result.confidence}")
    print(f"\n{'='*60}")
    print("FINAL VERDICT")
    print("="*60)
    print(result.verdict)

    await nexus.close()

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)
    print("\nThis is what developers get when they plug into NEXUS:")
    print(f"  - Structured verdict from 3 agent outputs")
    print(f"  - {result.loops_blocked} infinite loops blocked")
    print(f"  - {result.messages_filtered} low-quality messages filtered")
    print(f"  - Full audit trail with {result.audit_events} events")
    print(f"  - Zero rewrites to existing agent code")

if __name__ == "__main__":
    asyncio.run(main())