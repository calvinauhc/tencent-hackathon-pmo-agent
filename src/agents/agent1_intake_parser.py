"""
Agent 1 — Intake Parser. §2, §10.
Haiku tier (§16). Parses raw submission text into §3 fields; missing submitter/objective/solution
-> reject at intake with "incomplete information" (§10), never guessed.

Note on scope: this standalone parse_intake() function is exercised directly by tests/scenarios/
test_phase1.py against a real raw email. The 7 named scenarios still bypass it — pipeline.py hands
run_intake_to_gate2() an already-structured Project object from trial data, reusing only Agent 1's
REQUIRED_FIELDS constant for validation, not this LLM call. But the composer's "compose your own"
box (scripts/demo_engine.py's submit_freeform(), the left-panel dropdown redesign) DOES call this
function for real on whatever a person actually types — the genuine "parse raw text" entry point
this was always speced to be (§2), now genuinely reachable from the live demo, not just tests.

Fallback tier ("comparing Foo's repo" upversion, docs/comparing-foos-repo.md): a teammate's repo
(THENGFY/Transform-Office-Workflow) never crashes on unscripted input — its Agent 1 falls through
Gemini -> OpenAI -> a real deterministic regex parser. Our MOCK_MODE previously had no equivalent:
calling parse_intake() on any text without a hand-authored mock_response raised RuntimeError
outright, so the only inputs it could ever handle were ones someone had specifically pre-scripted.
_deterministic_fallback_parse() below closes that gap — same idea, adapted to our own field names
and this project's actual submission-email format (§12's SCENARIO_EMAILS), not a copy of theirs. It
also catches the case where a REAL Claude call succeeds at the network level but returns non-JSON
(src/llm/client.py's own `{"raw_text": ...}` fallback) — same "don't just crash" principle applied
to the real tier, not only the mock one.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.llm.client import llm

REQUIRED_FIELDS = ["submitter_name", "objective", "solution"]
ALL_PARSED_FIELDS = ["submitter_name", "team_members", "objective", "project_name", "solution",
                      "business_impact_usd", "capex_usd", "hypothesis_risk"]

SYSTEM_PROMPT = (
    "You parse a raw project-proposal submission (email or form text) into structured fields: "
    "submitter_name, team_members, objective, project_name, solution, business_impact_usd, "
    "capex_usd, hypothesis_risk. If a field is genuinely not stated, return null for it — never "
    "infer or guess a value that isn't in the text."
)


def _parse_usd(raw: str):
    """'$220,000' / '220,000 USD' / '0.5 million USD' -> 220000.0 / 500000.0. Returns None if
    nothing numeric is recoverable — never guesses a figure that isn't actually in the text."""
    if not raw:
        return None
    text = raw.strip()
    million = re.search(r"([\d.]+)\s*million", text, re.I)
    if million:
        try:
            return float(million.group(1)) * 1_000_000
        except ValueError:
            return None
    num = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not num:
        return None
    try:
        return float(num.group(0).replace(",", ""))
    except ValueError:
        return None


def _deterministic_fallback_parse(raw_text: str) -> dict:
    """High-precision pattern extraction against this project's own submission-email shape (see
    scripts/demo_engine.py's SCENARIO_EMAILS for the reference format this is built against) — a
    real, working extractor, not a stub. Only ever asked to handle text nobody pre-scripted a mock
    for, so it deliberately never guesses: an unmatched field stays None like every other path here,
    which naturally routes through the same "incomplete information" rejection as usual."""
    result = {f: None for f in ALL_PARSED_FIELDS}
    result["team_members"] = []

    name_match = (
        re.search(r"^From:\s*([A-Za-z][A-Za-z\s\.\'-]*?)(?:\s*<|\n|$)", raw_text, re.I | re.M) or
        re.search(r"\n\s*(?:Thanks|Regards|Best),?\s*\n\s*([A-Za-z][A-Za-z\s\.\'-]{1,40})\s*$", raw_text, re.I)
    )
    if name_match:
        result["submitter_name"] = name_match.group(1).strip()

    project_match = (
        re.search(r"Subject:\s*Proposal:\s*([^\n]+)", raw_text, re.I) or
        re.search(r"propos(?:e|ing|al)[^:]*:\s*([^\n.]+)", raw_text, re.I)
    )
    if project_match:
        result["project_name"] = project_match.group(1).strip()

    obj_match = re.search(r"Objective:\s*([^\n]+)", raw_text, re.I)
    if obj_match:
        result["objective"] = obj_match.group(1).strip()

    sol_match = re.search(r"Proposed solution:\s*([^\n]+)", raw_text, re.I)
    if sol_match:
        result["solution"] = sol_match.group(1).strip()

    impact_match = re.search(r"(?:business impact|size of price)[:\s]+\$?([\d.,]+\s*(?:million)?)", raw_text, re.I)
    if impact_match:
        result["business_impact_usd"] = _parse_usd(impact_match.group(1))

    capex_match = re.search(r"CAPEX[:\s]+\$?([\d.,]+\s*(?:million)?)", raw_text, re.I)
    if capex_match:
        result["capex_usd"] = _parse_usd(capex_match.group(1))

    risk_match = re.search(r"Risk:\s*([^\n]+)", raw_text, re.I)
    if risk_match:
        result["hypothesis_risk"] = risk_match.group(1).strip()

    team_match = re.search(r"Team:\s*([^\n]+)", raw_text, re.I)
    if team_match:
        team_raw = re.split(r"\s*[—-]\s*", team_match.group(1).strip())[0]  # drop " — Dept, Region" suffix
        result["team_members"] = [t.strip() for t in team_raw.split(",") if t.strip()]

    return result


def parse_intake(raw_text: str, mock_response=None):
    try:
        result, duration_ms = llm.call(
            agent_name="agent1_intake_parser",
            model_tier="haiku",
            system=SYSTEM_PROMPT,
            user=raw_text,
            mock_response=mock_response,
        )
    except RuntimeError:
        # MOCK_MODE active, no mock_response supplied — genuinely unscripted input. Previously this
        # raised straight past the caller; now it degrades to a real (if less accurate) answer.
        result, duration_ms = _deterministic_fallback_parse(raw_text), 0

    if set(result.keys()) == {"raw_text"}:
        # Real-mode call succeeded at the network level but didn't return parseable JSON
        # (src/llm/client.py's own fallback shape) — no usable structured fields, same situation as
        # above in effect, so the same fallback applies rather than rejecting every submission on a
        # technicality.
        result, duration_ms = _deterministic_fallback_parse(raw_text), duration_ms

    # Full field-by-field audit, not just REQUIRED_FIELDS — mirrors the self-audit a teammate's
    # ProjectSubmission.calculate_incomplete_fields() does, computed identically regardless of
    # whether `result` came from a real call, a scripted mock, or the fallback parser above.
    incomplete_fields = [f for f in ALL_PARSED_FIELDS if not result.get(f)]

    missing = [f for f in REQUIRED_FIELDS if not result.get(f)]
    if missing:
        return {
            "status": "rejected",
            "rejection_reason": f"Incomplete information — missing {', '.join(missing)}",
            "parsed_fields": result,
            "incomplete_fields": incomplete_fields,
        }, duration_ms
    return {"status": "pmo_review", "parsed_fields": result, "incomplete_fields": incomplete_fields}, duration_ms


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
