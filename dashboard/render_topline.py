"""
Topline dashboard (§9) — server-rendered to a static HTML file from real DB data.
Static output instead of a live Next.js dev server because this project folder is mounted over a
network filesystem that can't hold a running dev server session for the user to browse to (same
constraint documented in src/db/client.py) — §15's Next.js app is still the CodeBuddy-port target;
this is the equivalent view, rendered server-side once instead of served continuously.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.agents.agent10_success_predictor import predict_or_monitor

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
.nav a:hover{text-decoration:underline}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.card{background:#f5f4f0;border-radius:8px;padding:1rem}
.card .label{font-size:13px;color:#5f5e5a;margin-bottom:6px}
.card .num{font-size:24px;font-weight:600}
.riskmix{display:flex;gap:20px;align-items:center;padding:10px 14px;background:#f5f4f0;border-radius:8px;margin-bottom:14px;font-size:13px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.attention{background:#fcebeb;border:1px solid #f09595;border-radius:8px;padding:14px 16px;margin-bottom:20px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#5f5e5a;font-weight:400;font-size:12px;padding:8px 6px;border-bottom:1px solid #ddd}
td{padding:8px 6px;border-bottom:1px solid #eee}
.badge{font-size:11px;padding:2px 8px;border-radius:6px}
.green{background:#eaf3de;color:#3b6d11}.yellow{background:#faeeda;color:#854f0b}.red{background:#fcebeb;color:#a32d2d}.gray{background:#f1efe8;color:#5f5e5a}
"""

def render():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects WHERE status IN ('accepted','in_progress','completed','pmo_review','analysis') ORDER BY updated_at DESC LIMIT 20").fetchall()
    rows = [dict(r) for r in rows]

    # §5.3 — PMO's direct entry point into "what's waiting on a Gate 2 decision right now," not
    # just reachable through the batch-case demo buttons. Every project at status='analysis' IS
    # the queue (render_gate2_queue.py's get_gate2_queue()), so a plain count here stays truthful
    # without a second query definition to drift out of sync.
    gate2_pending_count = conn.execute("SELECT COUNT(*) AS n FROM projects WHERE status = 'analysis'").fetchone()["n"]

    # Agent 10 (§7) — only projects actually being tracked (accepted/in_progress/completed) are
    # eligible for a prediction at all; pmo_review/analysis rows haven't been accepted yet and stay
    # "—". Among tracked projects, predict_or_monitor() applies the age gate
    # (SUCCESS_PREDICTOR_MIN_AGE_DAYS): younger than that -> "Under monitoring", older -> a real
    # score computed fresh from current tracking-proxy fields, never a stale stored value.
    TRACKED_STATUSES = ("accepted", "in_progress", "completed")
    for r in rows:
        if r["status"] in TRACKED_STATUSES:
            pred = predict_or_monitor(r)
            r["_pred_status"] = pred["status"]
            r["_pred_score"] = pred["success_score"]
        else:
            r["_pred_status"] = "not_tracked"
            r["_pred_score"] = None

    scored = [r for r in rows if r["risk_indicator"]]
    active_count = len(rows)
    portfolio_value = sum(r["business_impact_usd"] or 0 for r in rows)
    capex_needed = sum(r["capex_usd"] or 0 for r in scored)
    capex_funded = sum((r["capex_usd"] or 0) * (r["capex_funded_pct"] or 0) / 100 for r in scored)
    capex_pct = round(100 * capex_funded / capex_needed) if capex_needed else 0
    # Only rows Agent 10 actually scored (not "under monitoring" or "not tracked") count toward the
    # average — including None/monitoring rows would silently drag the average toward a number that
    # isn't real for those projects.
    scores = [r["_pred_score"] for r in rows if r["_pred_status"] == "predicted"]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    risk_counts = {"green": 0, "yellow": 0, "red": 0, "in_review": 0}
    for r in rows:
        if r["risk_indicator"] in risk_counts:
            risk_counts[r["risk_indicator"]] += 1
        else:
            risk_counts["in_review"] += 1

    # Needs-attention must never miss a red project just because it fell outside the top-20
    # recency window used for the table below — query it separately, unbounded. Triggers on either
    # a red risk_indicator with an explicit help_needed note, or a red resource_indicator (a
    # staffing constraint is just as worth surfacing here as a risk one, per the same "flag it,
    # don't hide it" principle — §7.1 governance guardrail).
    all_red_rows = conn.execute(
        "SELECT * FROM projects WHERE (risk_indicator = 'red' AND help_needed IS NOT NULL AND help_needed != '') "
        "OR resource_indicator = 'red'"
    ).fetchall()
    reds = [dict(r) for r in all_red_rows]
    attention_html = ""
    if reds:
        def attention_note(r):
            if r["help_needed"]:
                return r["help_needed"]
            if r["resource_indicator"] == "red":
                return "Resource/staffing availability flagged red — team capacity is constrained."
            return ""
        items = "".join(
            f'<div style="margin-bottom:8px"><b>{r["project_name"]}</b> — {r["region"]} · {r["business_unit"]}<br>'
            f'<span style="color:#555">{attention_note(r)}</span></div>' for r in reds
        )
        attention_html = f'<div class="attention"><b>Needs attention — {len(reds)} red project(s)</b><br><br>{items}</div>'

    def badge(val):
        if not val:
            return '<span class="badge gray">in review</span>'
        return f'<span class="badge {val}">{val}</span>'

    def score_cell(r):
        if r["_pred_status"] == "predicted":
            return f'{r["_pred_score"]}'
        if r["_pred_status"] == "under_monitoring":
            return '<span style="color:#888;font-style:italic">Under monitoring</span>'
        return "—"

    def project_id_cell(r):
        # A real project ID only exists once Agent 7 has issued one (§2) — a row still sitting in
        # pmo_review/analysis genuinely doesn't have one yet, so this stays honest ("—") rather than
        # showing the submission ID as if it were the same thing.
        return r["project_id"] if r["project_id"] else "—"

    dashboard_dir = os.path.dirname(os.path.abspath(__file__))

    def name_cell(r):
        # Row links through to §9.1's live visualizer for this project (per §9's "Link to §9.1" —
        # clicking a project should go straight from "what's the portfolio look like" to "what is
        # this specific project doing right now" in one click). But only ONE project gets a fresh
        # visualizer_*.html per demo run (scripts/demo_engine.py renders just the scenario that was
        # actually run, not every trial row) — linking every row unconditionally would 404 for
        # every project except that one, so only link when the file genuinely exists on disk.
        link_id = r["project_id"] or r["submission_id"]
        vis_path = os.path.join(dashboard_dir, f"visualizer_{link_id}.html")
        name_html = f'<b>{r["project_name"]}</b>'
        if os.path.isfile(vis_path):
            return f'<a href="visualizer_{link_id}.html" style="color:#1a1a1a;text-decoration:none">{name_html}</a>'
        return name_html

    table_rows = "".join(
        f'<tr><td>{name_cell(r)}<br>'
        f'<span style="color:#378ADD;font-size:11px;font-family:monospace">{project_id_cell(r)}</span> · '
        f'<span style="color:#888;font-size:11px">{r["region"]} · {r["business_unit"]}</span></td>'
        f'<td style="text-align:right">${(r["business_impact_usd"] or 0)/1000:.0f}K</td>'
        f'<td>{badge(r["risk_indicator"])}</td><td>{badge(r["schedule_status"])}</td><td>{badge(r["resource_indicator"])}</td>'
        f'<td style="text-align:right">{r["capex_funded_pct"] or "—"}{"%" if r["capex_funded_pct"] else ""}</td>'
        f'<td style="text-align:right">{score_cell(r)}</td></tr>'
        for r in rows
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PMO Topline Dashboard</title><style>{CSS}</style></head>
<body>
<div class="nav"><a href="/" target="_top">← Composer</a><a href="activity.html">Portfolio activity feed</a><a href="gate2_queue.html">Gate 2 review queue{f' ({gate2_pending_count} pending)' if gate2_pending_count else ''}</a></div>
<h2>PMO portfolio — topline</h2>
<div class="cards">
<div class="card"><div class="label">Active projects</div><div class="num">{active_count}</div></div>
<div class="card"><div class="label">Portfolio value</div><div class="num">${portfolio_value/1e6:.2f}M</div></div>
<div class="card"><div class="label">CAPEX funded</div><div class="num">{capex_pct}%</div></div>
<div class="card"><div class="label">Avg success score</div><div class="num">{avg_score}</div></div>
</div>
<div class="riskmix">
<span>Risk mix</span>
<span><span class="dot" style="background:#639922"></span>{risk_counts['green']} green</span>
<span><span class="dot" style="background:#ef9f27"></span>{risk_counts['yellow']} yellow</span>
<span><span class="dot" style="background:#e24b4a"></span>{risk_counts['red']} red</span>
<span><span class="dot" style="background:#888"></span>{risk_counts['in_review']} in review</span>
</div>
{attention_html}
<table><tr><th>Project</th><th style="text-align:right">Size of price</th><th>Risk</th><th>Schedule</th><th>Resource</th><th style="text-align:right">CAPEX funded</th><th style="text-align:right">Score</th></tr>
{table_rows}
</table>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "topline.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, active_count

if __name__ == "__main__":
    path, count = render()
    print(f"rendered {path} with {count} projects")
