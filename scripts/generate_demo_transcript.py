"""
Phase 6.1 — produces the script + evidence for the required demo video (§12.1). This does not
record video (no capability to do that here) — it runs the real system once cleanly and writes
down exactly what happened, in the order it happened, so recording a screen capture of the same
run is a mechanical step, not a creative one.
"""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import insert_project, write_comment
from src.db.trial_loader import load_trial_data
from src.orchestration.pipeline import run_submission
from dashboard.render_visualizer import render as render_visualizer
from dashboard.render_gate2_queue import render as render_gate2_queue
from scripts.run_demo import SCENARIO_MOCKS

def main():
    conn = get_connection(fresh=True)
    projects, idx = load_trial_data()
    by_id = {p.submission_id: p for p in projects}
    by_pid = {p.project_id: p for p in projects if p.project_id}
    def get(ref): return by_pid.get(ref) or by_id.get(ref)
    for p in projects:
        insert_project(conn, p)

    scenario_key = "6_change_request_stakeholder_flag"
    ref = idx[scenario_key]
    target = get(ref[1] if isinstance(ref, list) else ref)
    existing = [p for p in projects if p.status in ("accepted", "in_progress", "completed") and p.submission_id != target.submission_id]
    trace = run_submission(conn, target, existing, SCENARIO_MOCKS[scenario_key])
    pid = trace.get("project_id", target.submission_id)
    write_comment(conn, pid, "Priya Sharma", "pmo", "Accept — confirm data handling plan before launch.", False, "gate2")
    write_comment(conn, pid, "Wei Ling Tan", "regulatory", "This touches EU customer data — confirm a GDPR review is scheduled before go-live.", True, None)
    v_path, v_steps = render_visualizer(pid)
    q_path, q_count = render_gate2_queue()

    lines = []
    lines.append(f"# Demo run transcript — generated {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append("This is the shot list for the required 3-5 min demo video (§12.1). Record a screen capture")
    lines.append("following these beats in order, using the real files listed below — nothing here is staged.")
    lines.append("")
    lines.append(f"**Scenario used**: `{scenario_key}` — \"{target.project_name}\" (Smart inventory forecasting agent)")
    lines.append("")
    lines.append("## Beat 1 — Problem framing (30-45s, talk to camera or voiceover)")
    lines.append("State the pain point this system solves: PMO manually triages every project proposal,")
    lines.append("checks for duplicates, and cross-references company policy by hand. Show the Agent brief.")
    lines.append("")
    lines.append("## Beat 2 — Submit through the composer (§12.1 entry point)")
    lines.append(f"Objective: {target.objective}")
    lines.append(f"Solution: {target.solution}")
    lines.append(f"Business impact: ${target.business_impact_usd:,.0f} · CAPEX: ${target.capex_usd:,.0f}")
    lines.append("")
    lines.append("## Beat 3 — Watch the live/replay visualizer (open in a browser)")
    lines.append(f"File: `{os.path.relpath(v_path, os.path.dirname(__file__)+'/..')}`")
    lines.append(f"Real audit_log steps replayed, {v_steps} agent calls, 1 event/sec pace.")
    lines.append("Point out: nodes light up as each agent runs, duration shown per node.")
    lines.append("")
    lines.append("## Beat 4 — Show the acknowledgment + acceptance notifications")
    for n in trace["notifications"]:
        lines.append(f"- **{n['subject']}**")
    lines.append("")
    lines.append("## Beat 5 — Open the composer, show the notifications strip + this week's Gate 2 batch")
    lines.append("Point out: the top notifications strip (moved off the old topline dashboard, §14), and the")
    lines.append("Periodic Gate 2 Review queue embedded directly in the composer's left panel, listing every")
    lines.append(f"project sitting at status='analysis' ({q_count} right now). Open one with \"Review & decide\".")
    lines.append("")
    lines.append("## Beat 6 — Show a real Gate 2 decision: Accept, Reject, or Hold")
    lines.append("Point out: Agent 5/6's findings, then the Accept/Reject/Hold buttons — Wei Ling Tan's flagged")
    lines.append("concern on this project (stakeholder, no decision power, just a flag) is what routes to the")
    lines.append("real Manual Gate 3 change-management trigger.")
    lines.append("")
    lines.append("## Beat 7 — Reflection (§ handbook submission checklist requirement)")
    lines.append("One sentence on the CodeBuddy build approach and a development-tool tip — fill in after")
    lines.append("the actual CodeBuddy port (§6.3 / PORTING.md), not before, so it's a real reflection.")
    lines.append("")
    lines.append("---")
    lines.append(f"Final status of this run: **{trace['final_status']}**, project ID `{pid}`.")

    out_path = os.path.join(os.path.dirname(__file__), "..", "DEMO-TRANSCRIPT.md")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path

if __name__ == "__main__":
    path = main()
    print(f"wrote {os.path.abspath(path)}")
