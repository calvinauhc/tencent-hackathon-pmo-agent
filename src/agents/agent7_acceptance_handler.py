"""Agent 7 — Acceptance Handler. §2, §8.2 guardrail 3. No LLM (§16) — deterministic, code-enforced."""
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.orchestration.state_machine import accept_project
from src.db.repositories import update_status
from src.notifications.templates import acceptance

def issue_project_id():
    return f"PRJ-2026-{random.randint(1000,9999)}"

def handle_acceptance(conn, submission_id, gate2_decision, project_name):
    new_status = accept_project(conn, submission_id, gate2_decision)
    row = conn.execute("SELECT project_id FROM projects WHERE submission_id = ?", (submission_id,)).fetchone()
    # Idempotent: a project_id assigned earlier in its lifecycle (e.g. at intake acknowledgment,
    # §11) is kept, not replaced — Agent 7 only *issues* one if none exists yet (§2: "issued only
    # at acceptance"). Reusing the audit trail's own project_id also keeps every prior audit_log
    # row and the visualizer/comment panel pointed at the same ID, not split across two.
    project_id = row["project_id"] if row and row["project_id"] else issue_project_id()
    conn.execute("UPDATE projects SET project_id = ? WHERE submission_id = ?", (project_id, submission_id))
    conn.commit()
    notification = acceptance(project_name, project_id)
    return {"status": new_status, "project_id": project_id, "notification": notification}
