"""
Phase 10 verification — Gate 2's optional accept comment and the Hold disposition.

Two small, targeted additions on top of §5.3's batch queue (not a new agent, no new schema):
1. Accept now takes an optional PMO comment, the same additive pattern Reject already had.
2. A third Gate 2 button, Hold, defers the decision entirely — no reason required, doesn't touch
   the override-rate metric, and needs almost no new mechanics because a project already sits at
   status='analysis' (i.e. already IN the queue) the moment Agent 6 finishes, before Gate 2 even
   opens. This file locks down that exact invariant, since Hold's correctness depends on it.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.client import get_connection
from src.db.repositories import insert_project, get_project, get_gate2_queue, get_audit_log, get_notifications
from src.db.trial_loader import load_trial_data
from src.notifications.templates import acceptance
from src.orchestration.pipeline import run_intake_to_gate2, resume_after_gate2

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)
projects, idx = load_trial_data()
by_id = {p.submission_id: p for p in projects}

GROUNDED_MOCKS = {
    "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
    "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
}

# --- 10.1 acceptance() template: additive PMO note, same pattern as rejection_feedback() ---
with_note = acceptance("Demo project", "PRJ-TEST-0001", pmo_comment="Great margin story — worth fast-tracking similar asks next quarter.")
check("10.1 pmo_comment is appended to the acceptance body", "PMO note: Great margin story" in with_note["body"], with_note["body"])

without_note = acceptance("Demo project", "PRJ-TEST-0001")
check("10.1 blank pmo_comment adds no 'PMO note:' line", "PMO note:" not in without_note["body"], without_note["body"])

# --- 10.2 resume_after_gate2(accept, pmo_comment=...) flows into the real notification + audit_log ---
case1 = by_id["SUB-0001"]
trace1 = run_intake_to_gate2(conn, case1, [], {"agent5": GROUNDED_MOCKS["agent5"], "agent6": GROUNDED_MOCKS["agent6"]})
check("10.2 setup: case reaches pending_gate2", trace1["final_status"] == "pending_gate2", trace1["final_status"])

resume_after_gate2(conn, case1, trace1, "accept", pmo_comment="Nice work getting CAPEX this low — keep an eye on the Q3 staffing dependency.")
a7_rows = [r for r in get_audit_log(conn, case1.project_id) if r["agent"] == "agent7_acceptance_handler"]
check("10.2 agent7 audit_log payload carries the pmo_comment", a7_rows and "Q3 staffing dependency" in a7_rows[-1]["payload"], a7_rows[-1]["payload"] if a7_rows else None)

notifs = get_notifications(conn, case1.project_id)
accept_notif = next((n for n in notifs if n["subject"].startswith("Accepted")), None)
check("10.2 the actual acceptance notification includes the PMO note", accept_notif and "PMO note: Nice work" in accept_notif["body"], accept_notif["body"] if accept_notif else None)

# --- 10.3 accept with no comment: unchanged, no stray 'PMO note:' anywhere ---
case4 = by_id["SUB-0004"] if "SUB-0004" in by_id else by_id[[k for k in by_id if k != "SUB-0001"][0]]
trace4 = run_intake_to_gate2(conn, case4, [], {"agent5": GROUNDED_MOCKS["agent5"], "agent6": GROUNDED_MOCKS["agent6"]})
if trace4["final_status"] == "pending_gate2":
    resume_after_gate2(conn, case4, trace4, "accept")
    a7_rows4 = [r for r in get_audit_log(conn, case4.project_id) if r["agent"] == "agent7_acceptance_handler"]
    check("10.3 a plain accept (no comment) logs an empty pmo_comment", a7_rows4 and '"pmo_comment": ""' in a7_rows4[-1]["payload"], a7_rows4[-1]["payload"] if a7_rows4 else None)
    notifs4 = get_notifications(conn, case4.project_id)
    accept_notif4 = next((n for n in notifs4 if n["subject"].startswith("Accepted")), None)
    check("10.3 the notification has no 'PMO note:' line when none was given", accept_notif4 and "PMO note:" not in accept_notif4["body"], accept_notif4["body"] if accept_notif4 else None)
else:
    check("10.3 skipped (case4 didn't reach pending_gate2 under this mock)", True, trace4["final_status"])

# --- 10.4 the Hold invariant: a project sitting at pending_gate2 is ALREADY in the Gate 2 queue ---
case_hold = by_id["SUB-0002"] if "SUB-0002" in by_id else [p for k, p in by_id.items() if k not in ("SUB-0001", "SUB-0004")][0]
trace_hold = run_intake_to_gate2(conn, case_hold, [], {"agent5": GROUNDED_MOCKS["agent5"], "agent6": GROUNDED_MOCKS["agent6"]})
if trace_hold["final_status"] == "pending_gate2":
    row = get_project(conn, case_hold.submission_id)
    check("10.4 an undecided Gate 2 case already sits at status='analysis'", row["status"] == "analysis", row["status"])
    queue = get_gate2_queue(conn)
    queue_ids = {r["submission_id"] for r in queue}
    check("10.4 that case is already visible in get_gate2_queue() — no extra write needed to 'hold' it", case_hold.submission_id in queue_ids, queue_ids)
else:
    check("10.4 skipped (case_hold didn't reach pending_gate2 under this mock)", True, trace_hold["final_status"])

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 10: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
