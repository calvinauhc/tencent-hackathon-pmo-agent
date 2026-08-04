"""
Phase 12 verification — "compose your own" freeform submission (§12.1 composer redesign).

Left panel went from 7 always-visible case cards + change management + batch sections stacked on
top of each other, to one dropdown covering all 9 (unchanged underlying actions, purely a
client-side view toggle — see scripts/demo_server.py's render_landing()), plus a genuinely new
capability: a From/Subject/Body compose box that runs typed text through the REAL pipeline, not a
predrafted trial-data anchor. This file locks down demo_engine.submit_freeform() — the new code
path, since the dropdown itself is markup/CSS with no new logic to test.

Two things this deliberately proves, not just asserts:
1. A submission that matches the compose box's placeholder shape genuinely parses (Agent 1's
   deterministic fallback, since MOCK_MODE has no mock_response for arbitrary text) and reaches a
   real Gate 2 decision — same as any named case.
2. A vague submission that does NOT match that shape genuinely fails to parse and gets the same
   real "incomplete information" rejection Case 5 demonstrates — not a crash, not a silent guess.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from src.db.client import get_connection
from src.db.repositories import get_project
import demo_engine

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

STRUCTURED_BODY = (
    "Objective: Vendor invoices are keyed in manually and slow down AP close.\n"
    "Proposed solution: An OCR and validation agent that reads invoices and pre-fills the AP system.\n\n"
    "Estimated business impact: $210,000. Estimated CAPEX: $55,000.\n"
    "Risk: No significant risk identified at this stage.\n\n"
    "Team: Priya Nair, Marcus Lee — Finance, Southeast Asia."
)

# --- 12.1 a well-structured freeform submission genuinely parses via Agent 1's real entry point ---
os.environ.pop("ANTHROPIC_API_KEY", None)  # this file exercises the MOCK_MODE fallback path specifically
result1 = demo_engine.submit_freeform(
    "Priya Nair <priya.nair@company.com>", "Proposal: Vendor invoice OCR agent", STRUCTURED_BODY,
)
check("12.1 a structured submission reaches a real outcome, not an error", result1.get("status") in ("pending_gate2", "terminal"), result1.get("status"))
check("12.1 Agent 1 actually extracted the objective from the typed text", result1["project"].objective == "Vendor invoices are keyed in manually and slow down AP close.", result1["project"].objective)
check("12.1 Agent 1 actually extracted the solution from the typed text", "OCR and validation agent" in (result1["project"].solution or ""), result1["project"].solution)
check("12.1 Agent 1 actually extracted business impact as a real number", result1["project"].business_impact_usd == 210000.0, result1["project"].business_impact_usd)
check("12.1 Agent 1 actually extracted CAPEX as a real number", result1["project"].capex_usd == 55000.0, result1["project"].capex_usd)
check("12.1 a complete, non-duplicate submission reaches a real Gate 2 decision", result1["status"] == "pending_gate2", result1)

# --- 12.2 the visualizer/gate2 pages actually got rendered under this submission's own id ---
if result1["status"] == "pending_gate2":
    gate2_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", f"gate2_{result1['submission_id']}.html")
    check("12.2 a real gate2_<id>.html file was rendered for this freeform submission", os.path.isfile(gate2_path), gate2_path)

# --- 12.3 a vague submission that doesn't match the placeholder shape genuinely fails to parse,
# and gets the SAME real rejection path Case 5 demonstrates — not a crash, not a guessed value ---
result2 = demo_engine.submit_freeform("someone@company.com", "idea", "I have a cool idea, thoughts?")
check("12.3 a vague submission reaches a terminal (not pending) outcome", result2["status"] == "terminal", result2["status"])
check("12.3 it's rejected for the real reason (incomplete info), not silently guessed", result2["trace"].get("final_status") == "rejected", result2["trace"].get("final_status"))
check("12.3 the rejection reason names the actual missing required fields", "submitter_name" in result2["trace"].get("rejection_reason", "") and "objective" in result2["trace"].get("rejection_reason", ""), result2["trace"].get("rejection_reason"))
check("12.3 incomplete_fields reflects every field Agent 1 couldn't find, not just the required ones", set(result2["incomplete_fields"]) == {"submitter_name", "team_members", "objective", "project_name", "solution", "business_impact_usd", "capex_usd", "hypothesis_risk"}, result2["incomplete_fields"])

# --- 12.4 Agent 2's duplicate check runs against the real seeded trial projects, not an empty list ---
conn = get_connection()
check("12.4 the trial fixture was seeded so duplicate-checking has real data to compare against", get_project(conn, "SUB-0001") is not None, "SUB-0001 present after a freeform run")

# --- 12.5 FREEFORM_MOCKS is a real dict shaped like every other agent5/agent6 mock in this file,
# so a freeform run can never hit MOCK_MODE's "no mock_response supplied" RuntimeError ---
check("12.5 FREEFORM_MOCKS has both agent5 and agent6 entries", set(demo_engine.FREEFORM_MOCKS.keys()) == {"agent5", "agent6"}, demo_engine.FREEFORM_MOCKS.keys())
check("12.5 the agent6 mock verdict is a real, valid verdict value", demo_engine.FREEFORM_MOCKS["agent6"]["verdict"] in ("aligned", "misaligned", "partially_aligned", "inconclusive"), demo_engine.FREEFORM_MOCKS["agent6"]["verdict"])

# --- 12.6 render_landing() exposes exactly the dropdown/panel structure the redesign promised:
# 7 named cases + change management + batch = 9 options, each with a matching panel, plus the
# compose box wired to the real /submit route ---
import demo_server
landing = demo_server.render_landing()
check("12.6 the dropdown has exactly 9 options (7 cases + change management + batch)", landing.count("<option") == 9, landing.count("<option"))
check("12.6 every option has a matching action-panel div", landing.count('class="action-panel') == 9, landing.count('class="action-panel'))
check("12.6 the compose box posts to the real /submit route", 'action="/submit"' in landing, '/submit' in landing)
check("12.6 the compose box has From/Subject/Body fields, not one raw textarea", 'name="from"' in landing and 'name="subject"' in landing and 'name="body"' in landing, None)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 12: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
