"""
Agent 1 — Intake Parser. §2, §10.
Haiku tier (§16). Parses raw submission text into §3 fields; missing submitter/objective/solution
-> reject at intake with "incomplete information" (§10), never guessed.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.llm.client import llm

REQUIRED_FIELDS = ["submitter_name", "objective", "solution"]

SYSTEM_PROMPT = (
    "You parse a raw project-proposal submission (email or form text) into structured fields: "
    "submitter_name, team_members, objective, project_name, solution, business_impact_usd, "
    "capex_usd, hypothesis_risk. If a field is genuinely not stated, return null for it — never "
    "infer or guess a value that isn't in the text."
)

def parse_intake(raw_text: str, mock_response=None):
    result, duration_ms = llm.call(
        agent_name="agent1_intake_parser",
        model_tier="haiku",
        system=SYSTEM_PROMPT,
        user=raw_text,
        mock_response=mock_response,
    )
    missing = [f for f in REQUIRED_FIELDS if not result.get(f)]
    if missing:
        return {
            "status": "rejected",
            "rejection_reason": f"Incomplete information — missing {', '.join(missing)}",
            "parsed_fields": result,
        }, duration_ms
    return {"status": "pmo_review", "parsed_fields": result}, duration_ms


# Real reference example from the conversation — the actual "Project 001" email
PROJECT_001_EMAIL = (
    "Hi PMO team, I would like to propose this project 001. The objective is to generate a size "
    "of price of 0.5 million USD and the estimated budget needed is 100,000 USD. There is no "
    "regulatory risk in implementation, however we need to wait for the approval before live. "
    "Let me know your thoughts."
)
PROJECT_001_MOCK_RESPONSE = {
    "submitter_name": None, "team_members": [], "objective": None,
    "project_name": "Project 001", "solution": None,
    "business_impact_usd": 500000, "capex_usd": 100000,
    "hypothesis_risk": "no regulatory risk (self-declared, unverified)",
}
