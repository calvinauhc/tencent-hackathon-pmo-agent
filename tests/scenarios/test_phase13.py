"""
Phase 13 verification — "the list is an interactive database" upversion:
1. A new `cancelled` status, distinct from `rejected` (schemas.py's Status.CANCELLED docstring
   explains why: rejected is PMO's own intake-time decision, cancelled is what happens to a project
   PMO already accepted, stopped later — usually because a post-acceptance update revealed it's
   slipping badly on timeline/cost/risk).
2. Gate 3 gets a third decision (Cancel) alongside Accept/Reject, reachable whenever a project
   update is escalated for PMO review.
3. Any accepted/in_progress project — not just Case 8/9's hardcoded PRJ-2026-0791 — can receive a
   real, typed update email via demo_engine.submit_project_update_freeform(), parsed by Agent 11's
   own deterministic parser (parse_update_email()), the same "never guess a field that isn't
   actually stated" convention Agent 1's fallback parser already established.
4. reset_demo() ("Revert back" button) wipes/reseeds the DB and clears stale per-run artifacts.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from src.db.client import get_connection
from src.db.repositories import insert_project, get_project, get_project_by_ref, get_change_request
from src.db.trial_loader import load_trial_data
from src.orchestration.state_machine import transition, IllegalTransitionError
from src.agents.agent11_update_logger import log_update, parse_update_email, _extract_submitter_name
from src.agents.agent12_change_evaluator import process_update, resolve_gate3
import demo_engine
import demo_server

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)
projects, idx = load_trial_data()
for p in projects:
    insert_project(conn, p)

# --- 13.1 state machine: cancelled is reachable from accepted/in_progress, terminal, illegal elsewhere ---
check("13.1 accepted -> cancelled is allowed", transition("accepted", "cancelled") == "cancelled")
check("13.1 in_progress -> cancelled is allowed", transition("in_progress", "cancelled") == "cancelled")
try:
    transition("draft", "cancelled")
    check("13.1 draft -> cancelled is illegal (nothing to cancel before acceptance)", False)
except IllegalTransitionError:
    check("13.1 draft -> cancelled is illegal (nothing to cancel before acceptance)", True)
try:
    transition("cancelled", "accepted")
    check("13.1 cancelled is terminal — nothing transitions out of it", False)
except IllegalTransitionError:
    check("13.1 cancelled is terminal — nothing transitions out of it", True)

# --- 13.2 parse_update_email(): extracts only what's actually stated, never guesses ---
full_email = (
    "From: Grace Lim <grace.lim@company.com>\nSubject: Update\n\n"
    "New launch date: 2027-03-01\nNew CAPEX: $95,000\nRisk: red\nSchedule: yellow\nResource: green\n\n"
    "Note: Vendor missed a milestone, we're reassessing the whole timeline."
)
fields, note = parse_update_email(full_email)
check("13.2 extracts expected_launch_date", fields.get("expected_launch_date") == "2027-03-01", fields)
check("13.2 extracts capex_usd as a real number", fields.get("capex_usd") == 95000.0, fields.get("capex_usd"))
check("13.2 extracts risk_indicator", fields.get("risk_indicator") == "red", fields.get("risk_indicator"))
check("13.2 extracts schedule_status", fields.get("schedule_status") == "yellow", fields.get("schedule_status"))
check("13.2 extracts resource_indicator", fields.get("resource_indicator") == "green", fields.get("resource_indicator"))
check("13.2 extracts the note", "reassessing the whole timeline" in (note or ""), note)

partial_email = "From: Someone\nSubject: x\n\nRisk: yellow\n\nNote: just a risk flag, nothing else changed."
fields2, note2 = parse_update_email(partial_email)
check("13.2 a partial email extracts ONLY the fields actually present, not fabricated defaults",
      set(fields2.keys()) == {"risk_indicator"}, fields2)

no_match_email = "From: x\nSubject: y\n\nHey, just wanted to say the project is going well!"
fields3, note3 = parse_update_email(no_match_email)
check("13.2 free prose with no labeled lines extracts nothing, doesn't guess", fields3 == {}, fields3)

check("13.2 _extract_submitter_name strips the email, keeps the name",
      _extract_submitter_name("Grace Lim <grace.lim@company.com>") == "Grace Lim")
check("13.2 _extract_submitter_name falls back to the raw string with no '<...>'",
      _extract_submitter_name("Grace Lim") == "Grace Lim")

# --- 13.3 resolve_gate3() cancel path: transitions the project, doesn't apply the proposed fields,
# writes a real cancellation notification distinct from decline ---
s1 = get_project(conn, "SUB-0001")  # accepted, PRJ-2026-0791
entry = log_update(conn, s1, {"capex_usd": 999000, "risk_indicator": "red"},
                    submitted_by="Grace Lim", note="Everything is going wrong.")
result = process_update(conn, entry, s1["project_name"], requested_by="Grace Lim")
check("13.3 setup: a bad-news update escalates to Gate 3", result["applied"] is False)

cancel_result = resolve_gate3(conn, result["change_request_id"], "cancel", s1["project_name"],
                               pmo_comment="Too far gone, pulling the plug.")
check("13.3 resolve_gate3(cancel) returns status=cancelled", cancel_result["status"] == "cancelled", cancel_result)
check("13.3 resolve_gate3(cancel) returns a real notification", "notification" in cancel_result and "cancelled" in cancel_result["notification"]["subject"].lower(), cancel_result.get("notification"))

s1_after = get_project(conn, "SUB-0001")
check("13.3 the project's status actually became cancelled", s1_after["status"] == "cancelled", s1_after["status"])
check("13.3 the proposed field changes did NOT apply (same non-effect as reject)", s1_after["capex_usd"] != 999000, s1_after["capex_usd"])
check("13.3 rejection_reason records why it was cancelled", "Cancelled by PMO" in (s1_after["rejection_reason"] or ""), s1_after["rejection_reason"])

cr_after = get_change_request(conn, result["change_request_id"])
check("13.3 the underlying change_request is marked rejected (the update itself never applied)", cr_after["status"] == "rejected", cr_after["status"])

# resolve_gate3() should reject a bad decision value outright, not silently no-op
try:
    resolve_gate3(conn, result["change_request_id"], "not_a_real_decision", s1_after["project_name"])
    check("13.3 resolve_gate3() rejects an invalid decision value", False)
except ValueError:
    check("13.3 resolve_gate3() rejects an invalid decision value", True)

# --- 13.4 submit_project_update_freeform(): works on ANY accepted/in_progress project, not just
# Case 8/9's hardcoded PRJ-2026-0791 ---
other_accepted = conn.execute(
    "SELECT * FROM projects WHERE status='accepted' AND project_id != 'PRJ-2026-0791' LIMIT 1"
).fetchone()
target_ref = other_accepted["project_id"] or other_accepted["submission_id"]
body = "New launch date: 2026-08-01\n\nNote: Ahead of schedule, pulling the date in."
result_free = demo_engine.submit_project_update_freeform(target_ref, "Test Submitter <t@company.com>", "Update", body)
check("13.4 a freeform update on a non-hardcoded project reaches a real outcome", "error" not in result_free, result_free)
check("13.4 it's a favorable change (earlier date) so it auto-applies", result_free.get("applied") is True, result_free)

# Any status outside accepted/in_progress proves the ineligibility check — §14 rebalanced the trial
# fixture's status mix (approval rate 20-30%, 5 rows parked in the Gate 2 queue), so this isn't tied
# to one specific status value that may or may not still exist in that mix.
ineligible_row = conn.execute("SELECT submission_id FROM projects WHERE status NOT IN ('accepted', 'in_progress') LIMIT 1").fetchone()
ineligible_ref = ineligible_row["submission_id"]
result_bad_status = demo_engine.submit_project_update_freeform(ineligible_ref, "x", "y", "Risk: red")
check("13.4 a non-accepted/in_progress project is correctly rejected as ineligible for updates",
      "error" in result_bad_status and "only accepted or in_progress" in result_bad_status["error"], result_bad_status)

result_no_fields = demo_engine.submit_project_update_freeform(target_ref, "x", "y", "just chatting, no real update here")
check("13.4 an email with no recognizable fields is rejected, not silently accepted as a no-op",
      "error" in result_no_fields, result_no_fields)

# --- 13.5 (§14) the update-compose panel lives in the composer's LEFT panel, with a real ghost-text
# body editor — the topline dashboard it used to live on is gone entirely now (not just missing this
# one panel; the whole page is retired). ---
topline_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "topline.html")
check("13.5 the topline dashboard is gone entirely (§14), not just missing the update panel",
      not os.path.isfile(topline_path))

landing = demo_server.render_landing()
check("13.5 the composer's left panel has the update-compose panel", 'id="update-compose"' in landing)
check("13.5 the update panel posts to the real route, targeting the middle panel",
      'action="/project-update/submit"' in landing and 'target="middle-frame"' in landing and 'id="u-form"' in landing)
check("13.5 the update panel only offers accepted/in_progress projects, not the ineligible one above",
      ineligible_ref not in landing.split('id="update-compose"')[1].split("</select>")[0])
check("13.5 the update panel's body uses the ghost-text editor (fixed label + greyed-out hint)",
      'id="u-body-editable"' in landing and 'class="lbl" contenteditable="false"' in landing)
check("13.5 the intake 'or submit your own' box also uses the ghost-text editor",
      'id="c-body-editable"' in landing and 'id="c-form"' in landing)

check("13.6 the composer's top notifications strip has a Revert back button", 'id="revert-btn"' in landing and "Revert back" in landing)
check("13.6 the revert button posts to the real /reset route, targeting the whole page", 'action="/reset"' in landing and 'target="_top"' in landing)

# --- 13.7 both ghost-text editors' assembled-text format (only "filled" rows join as "Label: value"
# lines, in order) round-trips correctly through the real parsers they're built against ---
from src.agents.agent1_intake_parser import _deterministic_fallback_parse

freeform_body = (
    "Objective: Manual invoice reconciliation takes 3 days a month\n"
    "Proposed solution: Automated matching against bank feed\n"
    "Estimated business impact: $220,000\n"
    "Estimated CAPEX: $45,000\n"
    "Risk: Vendor data format may vary by region\n"
    "Team: Grace Lim, Wei Ling Tan"
)
freeform_parsed = _deterministic_fallback_parse(
    f"From: Grace Lim <grace@company.com>\nSubject: Proposal: Invoice automation\n\n{freeform_body}"
)
check("13.7 ghost-editor-assembled freeform body parses all 6 fields correctly",
      freeform_parsed["objective"] == "Manual invoice reconciliation takes 3 days a month"
      and freeform_parsed["solution"] == "Automated matching against bank feed"
      and freeform_parsed["business_impact_usd"] == 220000.0
      and freeform_parsed["capex_usd"] == 45000.0
      and freeform_parsed["hypothesis_risk"] == "Vendor data format may vary by region"
      and freeform_parsed["team_members"] == ["Grace Lim", "Wei Ling Tan"],
      freeform_parsed)

ghost_update_body = "New launch date: 2027-01-01\n\nNote: Pulling the date in, ahead of schedule."
ghost_fields, ghost_note = parse_update_email(ghost_update_body)
check("13.7 ghost-editor-assembled update body (only 1 of 6 rows filled) parses correctly",
      ghost_fields == {"expected_launch_date": "2027-01-01"}
      and ghost_note == "Pulling the date in, ahead of schedule.",
      (ghost_fields, ghost_note))

# --- 13.8 reset_demo() wipes and reseeds cleanly ---
# Leave a stale artifact + a cancelled project in place, then confirm reset clears both.
stale_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "visualizer_STALE-TEST.html")
with open(stale_path, "w") as f:
    f.write("<html>stale</html>")
reset_result = demo_engine.reset_demo()
check("13.8 reset_demo() reseeds exactly the 20 curated trial projects", reset_result["projects_reseeded"] == 20, reset_result)
conn2 = get_connection()
count_after = conn2.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
statuses_after = {r["status"] for r in conn2.execute("SELECT status FROM projects").fetchall()}
check("13.8 the DB actually has 20 fresh rows post-reset", count_after == 20, count_after)
check("13.8 no cancelled projects survive a reset — back to the pristine seed", "cancelled" not in statuses_after, statuses_after)
check("13.8 the stale visualizer artifact was deleted", not os.path.isfile(stale_path))
gate2_queue_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "gate2_queue.html")
check("13.8 the standalone Gate 2 queue page was regenerated fresh", os.path.isfile(gate2_queue_path))
statuses_count_after = {}
for r in conn2.execute("SELECT status FROM projects").fetchall():
    statuses_count_after[r["status"]] = statuses_count_after.get(r["status"], 0) + 1
check("13.8 the reseeded fixture still has exactly 5 rows in this week's Gate 2 batch (§14)",
      statuses_count_after.get("analysis") == 5, statuses_count_after)

# --- 13.9 (§14 follow-up) a schedule-only update auto-applies (schedule_status isn't governance-
# relevant per Agent 12's GOVERNANCE_AXES) AND the new "active projects" panel actually shows the
# result — this is the real fix for the reported bug ("changed schedule from green to red, active
# listing didn't update"): there was never a persistence bug, there was no live view at all. ---
schedule_target = get_project_by_ref(conn2, "PRJ-2026-0791")
check("13.9 setup: PRJ-2026-0791 is accepted and schedule_status starts green post-reset",
      schedule_target["status"] == "accepted" and schedule_target["schedule_status"] == "green",
      (schedule_target["status"], schedule_target["schedule_status"]))

schedule_result = demo_engine.submit_project_update_freeform(
    "PRJ-2026-0791", "Grace Lim <grace.lim@company.com>", "Schedule update",
    "Schedule: red\n\nNote: Vendor slipped, flagging red."
)
check("13.9 a schedule-only change auto-applies (not governance-relevant on its own)",
      schedule_result.get("applied") is True and schedule_result.get("evaluation") == "favorable",
      schedule_result)

updated_target = get_project_by_ref(conn2, "PRJ-2026-0791")
check("13.9 the DB actually persisted red — confirms no persistence bug, ever",
      updated_target["schedule_status"] == "red", updated_target["schedule_status"])

landing_after_update = demo_server.render_landing()
check("13.9 the composer's left panel now has an active-projects panel", 'id="active-embed"' in landing_after_update)
active_block = landing_after_update.split('id="active-embed"')[1]
check("13.9 that panel shows PRJ-2026-0791's updated schedule_status (red) — the actual fix",
      'PRJ-2026-0791' in active_block and '<span class="badge red">red</span>' in active_block)

from dashboard.render_active_projects import render_active_fragment
standalone_fragment, standalone_count = render_active_fragment(conn2)
check("13.9 the standalone fragment (dashboard/active_projects.html's source) agrees",
      'PRJ-2026-0791' in standalone_fragment and standalone_count >= 1)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 13: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
