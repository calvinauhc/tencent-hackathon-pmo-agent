"""Phase 5 verification — BUILD-TASKS.md 5.1-5.2."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.trial_loader import load_trial_data
from src.agents.agent7_1_monthly_briefing import run_monthly_briefing

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

projects, idx = load_trial_data()
by_pid = {p.project_id: p for p in projects if p.project_id}
smart_inventory = by_pid["PRJ-2026-0842"]  # SE Asia, Operations
active = [p for p in projects if p.status in ("accepted", "in_progress")][:10]
if smart_inventory not in active:
    active.append(smart_inventory)

mock_insights = [
    {
        "project_id": "PRJ-2026-0842",
        "citation": "customer data processed by AI-driven systems operating in this region must be stored in-region",
        "insight": "This project's AI system operates in Southeast Asia — confirm storage location complies with the new in-region data residency requirement.",
        "source": "regulatory",
    },
    {
        "project_id": "PRJ-2026-0705",
        "citation": "this sentence does not exist anywhere in either source document",
        "insight": "Fabricated insight that should be dropped by the grounding guardrail.",
        "source": "political",
    },
]
out, duration_ms = run_monthly_briefing(active, mock_response=mock_insights)

check("5.1 grounded insight (real citation) is kept", any(i["project_id"] == "PRJ-2026-0842" for i in out["insights"]))
check("5.1 ungrounded/fabricated insight is dropped", not any(i["project_id"] == "PRJ-2026-0705" for i in out["insights"]))
check("5.1 dropped_ungrounded count is correct", out["dropped_ungrounded"] == 1, f"dropped={out['dropped_ungrounded']}")
check("5.1 doesn't force a comment on every project (only 1 kept, not 10+)", len(out["insights"]) == 1)

# --- 5.2 latency display: verify via a fresh demo run + visualizer render ---
import subprocess
proc = subprocess.run([sys.executable, "scripts/run_demo.py", "6_change_request_stakeholder_flag"],
                       cwd=os.path.join(os.path.dirname(__file__), "..", ".."), capture_output=True, text=True)
check("5.2 demo run for latency check succeeds", proc.returncode == 0)

vis_path = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "visualizer_PRJ-2026-0842.html")
with open(vis_path) as f:
    vis_html = f.read()
check("5.2 per-node duration_ms is shown", "steps[i].duration_ms + 'ms'" in vis_html)
check("5.2 running automated-time summary is computed", "Automated steps total" in vis_html)

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 5: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
