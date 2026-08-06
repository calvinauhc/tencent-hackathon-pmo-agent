"""
Phase 8 verification — §7.2.3 Agent 13 (OPL Composer) and §7.2.4's feedback into Agent 2
(duplicate detection) and Agent 5 (best-practice replication). Phase 3 of the change-management build.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.client import get_connection
from src.db.repositories import insert_project, get_project, get_project_by_ref, get_opl_kb_row
from src.db.trial_loader import load_trial_data
from src.orchestration.state_machine import transition
from src.db.repositories import update_status
from src.shared.schemas import Status
from src.agents.agent11_update_logger import log_update
from src.agents.agent13_opl_composer import compose_opl, publish_opl
from src.agents.agent2_duplicate_checker import check_duplicate, _text_of
from src.agents.agent5_business_impact_analyzer import analyze_business_impact
from src.knowledge.opl_loader import load_opl, extract_section

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)
projects, idx = load_trial_data()
by_id = {p.submission_id: p for p in projects}
for p in projects:
    insert_project(conn, p)

s1 = get_project(conn, "SUB-0001")  # case 1, accepted, PRJ-2026-0791

# --- 8.1 build real project_updates history, then transition accepted -> in_progress -> completed ---
log_update(conn, s1, {"capex_usd": 55000, "expected_launch_date": "2026-09-15"},
           submitted_by="Grace Lim", note="Vendor quote came in under budget; pulled the launch date in by a month.")
update_status(conn, s1["submission_id"], transition(Status.ACCEPTED.value, Status.IN_PROGRESS.value))
update_status(conn, s1["submission_id"], transition(Status.IN_PROGRESS.value, Status.COMPLETED.value))
s1_completed = get_project(conn, "SUB-0001")
check("8.1 project actually reached completed", s1_completed["status"] == "completed", s1_completed["status"])

# --- 8.2 compose_opl grounds citations against real source material, drops fabricated ones ---
mock = {
    "objective": "Reduce support ticket triage time.",
    "solution": "Automated triage/routing layer.",
    "timeline_narrative": "Launch was pulled in after a favorable vendor quote.",
    "outcome": "Delivered ahead of the original plan.",
    "what_worked": "Getting a vendor quote before locking the launch date bought real flexibility.",
    "citations": [
        "Vendor quote came in under budget; pulled the launch date in by a month.",  # real, grounded
        "The team invented a time machine to finish early.",  # fabricated, must be dropped
    ],
}
composed, dur = compose_opl(conn, s1_completed, mock_response=mock)
check("8.2 grounded citation is kept", "Vendor quote came in under budget; pulled the launch date in by a month." in composed["citations"])
check("8.2 fabricated citation is dropped", "The team invented a time machine to finish early." not in composed["citations"])
check("8.2 dropped_ungrounded count is correct", composed["dropped_ungrounded"] == 1, composed["dropped_ungrounded"])

# --- 8.3 publish_opl writes the .md file and a kb_documents row ---
opl_path = publish_opl(conn, s1_completed, composed)
check("8.3 OPL markdown file was written", os.path.isfile(opl_path))
with open(opl_path) as f:
    md = f.read()
check("8.3 markdown has the expected section headers", all(h in md for h in ["## Objective", "## Solution", "## Timeline", "## Outcome", "## What worked / what to reuse"]))
check("8.3 grounded citation appears in the published file", "Vendor quote came in under budget" in md)
check("8.3 fabricated citation does NOT appear in the published file", "time machine" not in md)

kb_row = get_opl_kb_row(conn, s1_completed["project_id"])
check("8.3 kb_documents row was written and marked active", kb_row is not None and kb_row["is_active"] == 1)

# --- 8.4 republishing supersedes the old kb_documents row rather than duplicating it ---
publish_opl(conn, s1_completed, composed)
active_rows = conn.execute(
    "SELECT COUNT(*) c FROM kb_documents WHERE doc_type='opl' AND project_id=? AND is_active=1",
    (s1_completed["project_id"],)
).fetchone()["c"]
check("8.4 republishing leaves exactly one active OPL row", active_rows == 1, active_rows)

# --- 8.5 opl_loader reads it back, and extract_section pulls just the reuse note ---
reloaded = load_opl(s1_completed["project_id"])
check("8.5 opl_loader.load_opl reads the published file back", "Reduce support ticket triage time." in reloaded)
excerpt = extract_section(reloaded, "What worked / what to reuse")
check("8.5 extract_section pulls only the what-worked note", "vendor quote" in excerpt.lower() and "## Outcome" not in excerpt, excerpt)

# --- 8.6 Agent 2's corpus text for a completed project now includes its OPL content ---
# _text_of expects attribute access (a Project object), not a dict row — its project_id must resolve
# to the same OPL file (PRJ-2026-0791) that was just published above.
s1_obj = by_id["SUB-0001"]
text_with_opl = _text_of(s1_obj)
check("8.6 Agent 2's corpus text for a completed project now includes its OPL content", "vendor quote" in text_with_opl.lower(), len(text_with_opl))

new_submission = by_id["SUB-0003"]  # any real distinct project object, reused just as a probe
# Build a synthetic incoming submission whose wording matches the OPL's rich text, not SUB-0001's
# terse original fields — this is the scenario the OPL feedback loop exists for (§7.2.4).
from copy import deepcopy
probe = deepcopy(new_submission)
probe.objective = "We want to reduce support ticket triage time the same way a past project did"
probe.project_name = "Support triage take two"
probe.solution = "Get a vendor quote before locking the launch date to buy schedule flexibility"
out_probe, _ = check_duplicate(probe, [s1_obj])
check("8.6 a submission worded like the OPL scores meaningfully similar to the completed project", out_probe["similarity"] > 0.05, f"similarity={out_probe['similarity']:.3f}")

# --- 8.7 Agent 5 surfaces a similar_past_project note when given one (deterministic passthrough) ---
spp = {"project_id": "PRJ-2026-0791", "project_name": "Customer support AI triage", "similarity": 0.42, "excerpt": excerpt}
mock5 = {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"}
out5, _ = analyze_business_impact(probe, mock_response=mock5, conn=conn, similar_past_project=spp)
check("8.7 Agent 5 output includes the similar_past_project note", out5.get("similar_past_project") == spp)

spp_empty_excerpt = {"project_id": "X", "project_name": "Y", "similarity": 0.1, "excerpt": ""}
out5b, _ = analyze_business_impact(probe, mock_response=mock5, conn=conn, similar_past_project=spp_empty_excerpt)
check("8.7 Agent 5 omits the note when there's no real excerpt to show", "similar_past_project" not in out5b)

# --- 8.8 Case 10's completion trigger (scripts/demo_engine.py's complete_project()) notifies the
# ORIGINATOR that the OPL is published, with a real link — not just a silent DB write nobody sees.
# Explicit ask: reply the originator that the OPL has been created, reachable via the given link. ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from src.notifications.templates import opl_published
import demo_engine

notif = opl_published("Customer support AI triage", "PRJ-2026-0791", "/dashboard/opl_PRJ-2026-0791.html")
check("8.8 opl_published() names the project and includes the real link",
      "Customer support AI triage" in notif["body"] and "/dashboard/opl_PRJ-2026-0791.html" in notif["body"])
check("8.8 opl_published() subject references the project id", "PRJ-2026-0791" in notif["subject"], notif["subject"])

conn2 = get_connection(fresh=True)
projects2, _idx2 = load_trial_data()
for p in projects2:
    insert_project(conn2, p)
result10 = demo_engine.complete_project("PRJ-2026-0791")
check("8.8 complete_project() returns a real notification addressed to the originator",
      result10.get("notification", {}).get("recipient") == "Grace Lim", result10.get("notification"))
check("8.8 complete_project()'s redirect carries the notification as query params (same relay "
      "pattern Case 8/9 use, since this never runs through the Live Execution Visualizer either)",
      "notif_subject=" in result10["redirect"]
      and result10["redirect"].startswith("/dashboard/opl_PRJ-2026-0791.html?"),
      result10["redirect"])

opl_page_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "opl_PRJ-2026-0791.html")
with open(opl_page_path) as f:
    opl_html = f.read()
check("8.8 the OPL page carries the notif_* relay script, so the composer's top notifications strip "
      "actually sees the notification (the redirect target needed its own copy of that relay)",
      "notif_subject" in opl_html and "window.parent.postMessage" in opl_html)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 8: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
