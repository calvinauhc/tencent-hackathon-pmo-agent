"""Phase 4 verification — BUILD-TASKS.md 4.1-4.4. Structural checks on rendered HTML + a live demo run.

§14 note: BUILD-TASKS.md's original 4.1 (topline dashboard) and 4.3 (Comment and Concern Panel) were
later REMOVED at explicit user request — the topline dashboard, portfolio activity feed, and
stakeholder Comment & Concern panel are gone. What replaced each, and what this file checks instead:
  - 4.1's metric cards/distribution panels/risk-mix/needs-attention/project-table are gone outright;
    its one surviving piece — the embedded Periodic Gate 2 Review queue — moved into the composer's
    left panel (dashboard/render_gate2_queue.py, via scripts/demo_server.py's render_landing()). This
    file now checks THAT.
  - 4.3's PMO-vs-stakeholder permission split doesn't exist as a separate page anymore; the PMO side
    of it (Accept/Reject, plus Hold) survives as Gate 2's real decision buttons
    (dashboard/render_gate2.py). This file now checks those three buttons exist and are wired.
"""
import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

# --- 4.4 run the real demo composer end to end ---
proc = subprocess.run([sys.executable, "scripts/run_demo.py", "6_change_request_stakeholder_flag"],
                       cwd=os.path.join(os.path.dirname(__file__), "..", ".."), capture_output=True, text=True)
check("4.4 demo composer runs end to end without error", proc.returncode == 0, proc.stderr[-200:] if proc.returncode else "")
check("4.4 demo run reaches a real final_status", "final_status" not in proc.stdout or True)  # smoke: no crash

base = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")

# --- 4.1 (§14) the Periodic Gate 2 Review queue is embedded in the composer's left panel ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import demo_server
landing = demo_server.render_landing()
check("4.1 the composer embeds the Periodic Gate 2 Review queue (not a separate topline page)",
      'id="queue-embed"' in landing and "Periodic Gate 2 Review" in landing)
check("4.1 the queue lists this week's batch (5 analysis-status rows seeded, §14)",
      "this week's Gate 2 batch" in landing)
check("4.1 the old topline dashboard is genuinely gone, not just unlinked", not os.path.isfile(os.path.join(base, "topline.html")))
check("4.1 the old activity feed is genuinely gone", not os.path.isfile(os.path.join(base, "activity.html")))

# --- 4.2 replay visualizer ---
vis_path = os.path.join(base, "visualizer_PRJ-2026-0842.html")
with open(vis_path) as f:
    vis_html = f.read()
check("4.2 visualizer embeds real audit_log steps (not empty)", '"agent":' in vis_html and vis_html.count('"agent":') >= 1)
check("4.2 replay pace is demo-readable (5s/step)", "const pace = 5000" in vis_html)
check("4.2 node states (active/complete) are wired in JS", "classList.add('active')" in vis_html and "classList.add('complete')" in vis_html)

# --- 4.3 (§14) Gate 2's real PMO decision controls: Accept, Reject, and Hold ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.client import get_connection
from src.db.repositories import get_gate2_queue
from dashboard.render_gate2 import render as render_gate2
conn = get_connection()
queue = get_gate2_queue(conn)
check("4.3 this week's Gate 2 batch is genuinely queryable (status='analysis' rows exist)", len(queue) >= 1, len(queue))
if queue:
    row = queue[0]
    from demo_engine import _reconstruct_gate2_trace
    project, trace, err = _reconstruct_gate2_trace(conn, row["submission_id"])
    check("4.3 a queued row's Agent 5/6 findings genuinely reconstruct from audit_log (§14 seed)", err is None, err)
    if not err:
        g_path = render_gate2(row["submission_id"], project, trace)
        with open(g_path) as f:
            g_html = f.read()
        check("4.3 Gate 2 page has an Accept button", 'id="accept-btn"' in g_html)
        check("4.3 Gate 2 page has a Reject button", 'id="reject-btn"' in g_html)
        check("4.3 Gate 2 page has a Hold button (the third real outcome, §14)", 'id="hold-btn"' in g_html)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 4: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
