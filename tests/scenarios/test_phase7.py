"""
Phase 7 verification — §7.2.2 Agent 12 (Change Evaluator) and the real Manual Gate 3, Phase 2 of the
change-management build. Agent 13 (OPL) is a later phase, not covered here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.client import get_connection
from src.db.repositories import insert_project, get_project, get_change_request, get_pending_change_requests, get_notifications
from src.db.trial_loader import load_trial_data
from src.agents.agent11_update_logger import log_update
from src.agents.agent12_change_evaluator import evaluate, process_update, resolve_gate3

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)
projects, idx = load_trial_data()
for p in projects:
    insert_project(conn, p)

# --- 7.1 evaluate(): pure favorable/unfavorable logic ---
v1 = evaluate({"capex_usd": 60000}, {"capex_usd": 55000})
check("7.1 lower CAPEX alone is favorable", v1["evaluation"] == "favorable", v1["reason"])

v2 = evaluate({"risk_indicator": "green"}, {"risk_indicator": "yellow"})
check("7.1 risk regressing alone is needs_authorization", v2["evaluation"] == "needs_authorization", v2["reason"])

v3 = evaluate({"expected_launch_date": "2026-10-15", "capex_usd": 60000},
              {"expected_launch_date": "2026-09-01", "capex_usd": 65000})
check("7.1 earlier timeline but higher CAPEX -> needs_authorization (AND rule, not OR)", v3["evaluation"] == "needs_authorization", v3["reason"])

v4 = evaluate({"expected_launch_date": "2026-10-15", "capex_usd": 60000, "risk_indicator": "yellow"},
              {"expected_launch_date": "2026-09-01", "capex_usd": 55000, "risk_indicator": "green"})
check("7.1 strict improvement on all three axes -> favorable", v4["evaluation"] == "favorable" and len(v4["axis_results"]) == 3, v4["reason"])

v5 = evaluate({"schedule_status": "yellow"}, {"schedule_status": "green"})
check("7.1 only a non-governance field (schedule_status) changing -> favorable (nothing to gate)", v5["evaluation"] == "favorable" and v5["axis_results"] == {}, v5["reason"])

v6 = evaluate({"capex_usd": 60000}, {"capex_usd": 60000})
check("7.1 identical value on a touched field (no real change) -> not favorable", v6["evaluation"] == "needs_authorization", v6["reason"])

# --- 7.2 process_update(): favorable path actually applies to the live projects row ---
s1 = get_project(conn, "SUB-0001")  # accepted, capex 60000, launch 2026-10-15, risk green
entry_fav = log_update(conn, s1, {"capex_usd": 55000, "expected_launch_date": "2026-09-15"},
                        submitted_by="Grace Lim", note="Vendor quote came in under budget.")
result_fav = process_update(conn, entry_fav, s1["project_name"], requested_by="Grace Lim")
check("7.2 favorable update is applied immediately", result_fav["applied"] is True and result_fav["change_request_id"] is None)

s1_after = get_project(conn, "SUB-0001")
check("7.2 the live projects row actually reflects the new values", s1_after["capex_usd"] == 55000 and s1_after["expected_launch_date"] == "2026-09-15")

notifs = get_notifications(conn, s1_after["project_id"])
check("7.2 an auto-applied notification was sent", any("Auto-applied" in n["subject"] for n in notifs), [n["subject"] for n in notifs])

# --- 7.3 process_update(): unfavorable path opens a real Gate 3, does NOT touch the live row ---
entry_unfav = log_update(conn, s1_after, {"capex_usd": 90000, "risk_indicator": "yellow"},
                          submitted_by="Grace Lim", note="Scope grew; new dependency risk.")
result_unfav = process_update(conn, entry_unfav, s1_after["project_name"], requested_by="Grace Lim")
check("7.3 unfavorable update is NOT applied", result_unfav["applied"] is False)
check("7.3 a change_request was opened", result_unfav["change_request_id"] is not None)

s1_still = get_project(conn, "SUB-0001")
check("7.3 the live row is untouched pending Gate 3", s1_still["capex_usd"] == 55000 and s1_still["risk_indicator"] == "green")

cr = get_change_request(conn, result_unfav["change_request_id"])
check("7.3 change_requests row is status=pending", cr["status"] == "pending", cr["status"])

pending = get_pending_change_requests(conn)
check("7.3 the pending list surfaces it", any(p["id"] == result_unfav["change_request_id"] for p in pending), len(pending))

# --- 7.4 Gate 3 resolution: Accept applies the change PMO just authorized ---
resolve_gate3(conn, result_unfav["change_request_id"], "accept", s1_still["project_name"], pmo_comment="Approved — scope growth is justified.")
s1_final = get_project(conn, "SUB-0001")
check("7.4 Gate 3 accept applies the originally-captured after_state", s1_final["capex_usd"] == 90000 and s1_final["risk_indicator"] == "yellow")

cr_resolved = get_change_request(conn, result_unfav["change_request_id"])
check("7.4 change_requests row is marked approved", cr_resolved["status"] == "approved")

notifs2 = get_notifications(conn, s1_final["project_id"])
check("7.4 requester was notified the change was authorized", any("authorized" in n["subject"].lower() for n in notifs2), [n["subject"] for n in notifs2])

# --- 7.5 Gate 3 resolution: Reject leaves the live row untouched ---
entry_unfav2 = log_update(conn, s1_final, {"capex_usd": 150000}, submitted_by="Grace Lim", note="Vendor re-quote, much higher.")
result_unfav2 = process_update(conn, entry_unfav2, s1_final["project_name"], requested_by="Grace Lim")
resolve_gate3(conn, result_unfav2["change_request_id"], "reject", s1_final["project_name"], pmo_comment="Too large an increase — resubmit with a revised scope.")
s1_after_reject = get_project(conn, "SUB-0001")
check("7.5 Gate 3 reject leaves the live projects row unchanged", s1_after_reject["capex_usd"] == 90000, s1_after_reject["capex_usd"])

cr_rejected = get_change_request(conn, result_unfav2["change_request_id"])
check("7.5 change_requests row is marked rejected", cr_rejected["status"] == "rejected")

# --- 7.6 double-resolving the same change_request raises, doesn't silently double-apply ---
raised = False
try:
    resolve_gate3(conn, result_unfav2["change_request_id"], "accept", s1_final["project_name"])
except ValueError:
    raised = True
check("7.6 resolving an already-resolved change_request raises rather than double-applying", raised)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 7: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
