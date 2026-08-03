"""
Phase 6 verification — §7.2.1 Agent 11 (Update Logger), Phase 1 of the change-management build.
Agent 12 (favorable/unfavorable), Gate 3, and Agent 13 (OPL) are later phases, not covered here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.client import get_connection
from src.db.repositories import insert_project, get_project
from src.db.trial_loader import load_trial_data
from src.agents.agent11_update_logger import diff_update, log_update, UPDATABLE_FIELDS

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

conn = get_connection(fresh=True)
projects, idx = load_trial_data()
for p in projects:
    insert_project(conn, p)

s1 = get_project(conn, "SUB-0001")  # case 1 — accepted, green/green/green, capex 60000

# --- 6.1 diff_update is a pure function: only changed fields are reported ---
before, after, changed = diff_update(s1, {
    "expected_launch_date": "2026-09-01",  # earlier than the seeded 2026-10-15 -> real change
    "capex_usd": 60000,                     # same as baseline -> not a change
})
check("6.1 diff only reports fields that actually differ", changed == ["expected_launch_date"], f"changed={changed}")
check("6.1 before_state captures the old value", before.get("expected_launch_date") == "2026-10-15", before)
check("6.1 after_state captures the new value", after.get("expected_launch_date") == "2026-09-01", after)

# --- 6.2 fields outside UPDATABLE_FIELDS are silently ignored, not applied ---
before2, after2, changed2 = diff_update(s1, {"project_name": "Renamed project", "region": "Europe"})
check("6.2 non-updatable fields never appear in a diff", changed2 == [], f"changed={changed2}")

# --- 6.3 no-op submission (identical values) produces an empty diff ---
before3, after3, changed3 = diff_update(s1, {"risk_indicator": s1["risk_indicator"], "schedule_status": s1["schedule_status"]})
check("6.3 submitting unchanged values produces no diff", changed3 == [], f"changed={changed3}")

# --- 6.4 log_update writes an unconditional, append-only row to project_updates ---
entry = log_update(conn, s1, {
    "capex_usd": 55000,          # lower than baseline (60000) -> a real, favorable-looking change
    "expected_launch_date": "2026-09-01",
}, submitted_by="Grace Lim", note="Vendor quote came in under budget; pulled launch in by a month.")
check("6.4 log_update returns the fields it actually changed", set(entry["fields_changed"]) == {"capex_usd", "expected_launch_date"}, entry["fields_changed"])
check("6.4 log_update returns a real row id", isinstance(entry["id"], int) and entry["id"] > 0, entry["id"])

from src.db.repositories import get_project_updates
rows = get_project_updates(conn, s1["project_id"])
check("6.5 the row is actually persisted in project_updates", len(rows) == 1, f"count={len(rows)}")
check("6.5 persisted before_state/after_state round-trip correctly", rows[0]["before_state"]["capex_usd"] == 60000 and rows[0]["after_state"]["capex_usd"] == 55000)
check("6.5 evaluation/applied are unset — Agent 11 never judges the change itself", rows[0]["evaluation"] is None and rows[0]["applied"] == 0)

# --- 6.6 a second, unrelated update on the same project appends rather than overwrites ---
log_update(conn, s1, {"risk_indicator": "yellow"}, submitted_by="Daniel Ho", note="Vendor integration slipping; watching closely.")
rows2 = get_project_updates(conn, s1["project_id"])
check("6.6 project_updates is append-only across multiple submissions", len(rows2) == 2, f"count={len(rows2)}")

# --- 6.7 Agent 11 never touches the live `projects` row ---
s1_after = get_project(conn, "SUB-0001")
check("6.7 Agent 11 never writes to the projects table itself", s1_after["capex_usd"] == 60000 and s1_after["expected_launch_date"] == "2026-10-15", "capex/launch unchanged on the live row — only Agent 12 (Phase 2) will apply this")

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 6: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
