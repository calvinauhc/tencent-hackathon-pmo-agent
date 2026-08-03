"""
Phase 9 verification — §5.3 Periodic Gate 2 Review: the weekly batch queue, the regional CAPEX
rollup, the policy-based fast-track exception, and the logged PMO override.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from src.db.client import get_connection
from src.db.repositories import get_project, get_gate2_queue, get_open_gate2_batch, get_audit_log
from dashboard.render_gate2_queue import _compute_region_rollups
import demo_engine as eng

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)

# --- 9.1 is_fast_track reads the real playbook-mirroring threshold ---
check("9.1 fast-track project (<$50K) is correctly identified", eng.is_fast_track(eng.BATCH_CASE_PROJECTS["9"]))
check("9.1 non-fast-track project (>=$50K) is correctly identified", not eng.is_fast_track(eng.BATCH_CASE_PROJECTS["8a"]))

# --- 9.2 case 8a/8b land in the queue; case 9 opens immediately (not queued) ---
r8a = eng.run_batch_case("8a")
check("9.2 case 8a lands in the queue", r8a.get("queued") is True, r8a)
r8b = eng.run_batch_case("8b")
check("9.2 case 8b lands in the queue", r8b.get("queued") is True, r8b)
r9 = eng.run_batch_case("9")
check("9.2 case 9 (fast-track) does NOT land in the queue", r9.get("queued") is False, r9)
check("9.2 case 9 carries a fast-track exception_reason", "fast-track" in (r9.get("exception_reason") or ""), r9.get("exception_reason"))
r10 = eng.run_batch_case("10")
check("9.2 case 10 lands in the queue (override candidate)", r10.get("queued") is True, r10)

queue = get_gate2_queue(conn)
queued_ids = {r["submission_id"] for r in queue}
check("9.2 queue contains 8a, 8b, 10", {"SUB-CASE8A", "SUB-CASE8B", "SUB-CASE10"}.issubset(queued_ids), queued_ids)

# --- 9.3 re-clicking an already-run batch case doesn't re-run the pipeline or error ---
r8a_again = eng.run_batch_case("8a")
check("9.3 re-running an already-queued case is a safe no-op, not an error", "error" not in r8a_again, r8a_again)

# --- 9.4 regional rollup math: two SE Asia asks summed together against the shared budget ---
rollups = _compute_region_rollups(conn, queue)
check("9.4 Southeast Asia rollup exists", "Southeast Asia" in rollups)
sea = rollups["Southeast Asia"]
check("9.4 queued_ask sums BOTH case 8a and 8b together, not just one", sea["queued_ask"] == 300000 + 280000, sea["queued_ask"])
check("9.4 total_if_all_approved = committed + queued_ask", sea["total_if_all_approved"] == sea["committed"] + sea["queued_ask"])
check("9.4 a recommended prioritization lens is present", sea["recommended_lens"] in ("low_risk_low_capex_first", "best_roi_ratio_first"), sea["recommended_lens"])

# --- 9.5 batch open/close lifecycle ---
check("9.5 no batch open initially", get_open_gate2_batch(conn) is None)
open_result = eng.open_batch()
batch = get_open_gate2_batch(conn)
check("9.5 open_batch() actually opens one", batch is not None)
open_again = eng.open_batch()
check("9.5 opening again while one is open doesn't create a second batch", get_open_gate2_batch(conn)["id"] == batch["id"])

# --- 9.6 review_queued_project requires an open batch, and reconstructs real Agent 5/6 findings ---
review = eng.review_queued_project("SUB-CASE8A")
check("9.6 review succeeds while a batch is open", "error" not in review, review)
check("9.6 review reconstructs the project's real Agent 5 finding", review["trace"]["agent5"].get("margin_impact") == "positive", review["trace"].get("agent5"))
check("9.6 review tags the current open batch id", review["gate2_batch_id"] == batch["id"])

eng.close_batch(batch["id"])
check("9.6 no batch open after closing", get_open_gate2_batch(conn) is None)
review_no_batch = eng.review_queued_project("SUB-CASE8B")
check("9.6 review fails once no batch is open", "error" in review_no_batch and "no batch" in review_no_batch["error"].lower(), review_no_batch)

# --- 9.7 override works without an open batch, but requires a reason ---
override_no_reason = eng.override_queued_project("SUB-CASE10", "")
check("9.7 override without a reason is rejected", "error" in override_no_reason, override_no_reason)
override_ok = eng.override_queued_project("SUB-CASE10", "Hard regulatory deadline this quarter.")
check("9.7 override with a reason succeeds even though no batch is open", "error" not in override_ok, override_ok)
check("9.7 override carries the logged reason, not a batch id", override_ok["exception_reason"] == "Hard regulatory deadline this quarter." and override_ok["gate2_batch_id"] is None)

# --- 9.8 the resolution's audit_log entry actually carries gate2_batch_id/exception_reason through ---
project, trace = review["project"], review["trace"]
eng.resume_scenario(project, trace, "accept", gate2_batch_id=review["gate2_batch_id"], exception_reason=None)
a7_rows = [r for r in get_audit_log(conn, project.project_id or project.submission_id) if r["agent"] == "agent7_acceptance_handler"]
check("9.8 accepted-via-batch decision's audit_log entry carries the batch id", a7_rows and str(batch["id"]) in a7_rows[-1]["payload"], a7_rows[-1]["payload"] if a7_rows else None)

project10, trace10 = override_ok["project"], override_ok["trace"]
eng.resume_scenario(project10, trace10, "accept", gate2_batch_id=None, exception_reason="Hard regulatory deadline this quarter.")
a7_rows10 = [r for r in get_audit_log(conn, project10.project_id or project10.submission_id) if r["agent"] == "agent7_acceptance_handler"]
check("9.8 accepted-via-override decision's audit_log entry carries the reason", a7_rows10 and "Hard regulatory deadline" in a7_rows10[-1]["payload"], a7_rows10[-1]["payload"] if a7_rows10 else None)

# --- 9.9 once resolved, a project drops out of the queue ---
queue_after = get_gate2_queue(conn)
queue_after_ids = {r["submission_id"] for r in queue_after}
check("9.9 SUB-CASE8A no longer sits in the queue after being accepted", "SUB-CASE8A" not in queue_after_ids, queue_after_ids)
check("9.9 SUB-CASE10 no longer sits in the queue after being accepted", "SUB-CASE10" not in queue_after_ids, queue_after_ids)
check("9.9 SUB-CASE8B (not yet decided) still sits in the queue", "SUB-CASE8B" in queue_after_ids, queue_after_ids)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 9: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
