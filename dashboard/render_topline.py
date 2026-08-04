"""
Topline dashboard (§9) — server-rendered to a static HTML file from real DB data.
Static output instead of a live Next.js dev server because this project folder is mounted over a
network filesystem that can't hold a running dev server session for the user to browse to (same
constraint documented in src/db/client.py) — §15's Next.js app is still the CodeBuddy-port target;
this is the equivalent view, rendered server-side once instead of served continuously.

Two additions on top of the original topline (both requested together, see docs/comparing-foos-repo.md):
1. A dark metric-card + percentage-bar summary block (Total Projects / Portfolio value / Approved
   rate / Avg success likelihood), styled after a reference dashboard screenshot. Adopted the
   screenshot's CARD/BAR LAYOUT, not a full dark re-theme of the app — every other page (composer,
   visualizer, activity, Gate 2/3) stays the existing light-cream look, so this is a scoped judgment
   call, not a silent app-wide restyle.
2. §5.3's Periodic Gate 2 Review queue, embedded directly (dashboard/render_gate2_queue.py's
   render_queue_fragment()) between "needs attention" and the project table — the composer's old
   left-panel batch buttons (cases 8a/8b/9/10) are gone; this embedded view plus its own
   Open/Close-batch and Review/Override buttons are now the one real entry point.

The distribution panels (below the metric cards) are four real, computed-from-real-data governance
views, not a fixed pair — Status Distribution plus three requested "top management purview" metrics:
CAPEX Funding Coverage (fully/partially/unfunded, from capex_funded_pct), Predictive Portfolio Health
(Agent 10's real per-project success-score bucketed High/Medium/Low/Under monitoring/Not yet tracked
— the single "Avg success likelihood" card above can hide a bimodal spread this doesn't), and
Portfolio Value by Business Unit (real business_impact_usd summed per BU, a concentration-risk view).
A fourth panel, Strategic Coverage (Aligned vs Orphaned, from Agent 6's audit_log verdict), was built
and then removed at the user's request — the underlying Agent 6 alignment-verdict lookup
(get_latest_agent_payload) is no longer imported here. Three OTHER requested metrics — Allocation
Variance (Actual vs Planned Capacity), CapEx/OpEx Strategic Ratio, and Cross-Functional Dependency
Resolution Time — were never built at all: none of the fields they'd need (planned/actual capacity,
OpEx, dependency tracking) exist anywhere in this schema (src/shared/schemas.py's Project dataclass),
and fabricating numbers for them would break this project's own "never guess/never invent a figure"
discipline. Add the real fields first if these become genuinely wanted.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.agents.agent10_success_predictor import predict_or_monitor
from dashboard.render_gate2_queue import render_queue_fragment

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
.nav a:hover{text-decoration:underline}

.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}
.mcard{background:#12213f;border-radius:10px;padding:14px 16px;color:#fff}
.mcard .mlabel{font-size:11px;color:#93a8d0;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
.mcard .mnum{font-size:26px;font-weight:700}
.distros{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-bottom:20px}
.distro{background:#12213f;border-radius:10px;padding:14px 16px;color:#fff}
.distro h4{font-size:11px;margin:0 0 12px;color:#93a8d0;text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.drow{margin-bottom:9px}
.drow:last-child{margin-bottom:0}
.dlabel{display:flex;justify-content:space-between;font-size:12px;color:#dbe4f5;margin-bottom:4px}
.dbar{height:6px;border-radius:3px;background:#24365f;overflow:hidden}
.dbar-fill{height:100%;border-radius:3px}

.riskmix{display:flex;gap:20px;align-items:center;padding:10px 14px;background:#f5f4f0;border-radius:8px;margin-bottom:14px;font-size:13px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.attention{background:#fcebeb;border:1px solid #f09595;border-radius:8px;padding:14px 16px;margin-bottom:20px}
.section-h{font-size:14px;margin:22px 0 10px;color:#1a1a1a}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#5f5e5a;font-weight:400;font-size:12px;padding:8px 6px;border-bottom:1px solid #ddd}
th.sortable{cursor:pointer;user-select:none}
th.sortable:hover{color:#378ADD}
th.sortable .arrow{font-size:9px;margin-left:3px;opacity:.55}
td{padding:8px 6px;border-bottom:1px solid #eee}
.badge{font-size:11px;padding:2px 8px;border-radius:6px}
.green{background:#eaf3de;color:#3b6d11}.yellow{background:#faeeda;color:#854f0b}.red{background:#fcebeb;color:#a32d2d}.gray{background:#f1efe8;color:#5f5e5a}

/* Embedded Gate 2 queue (dashboard/render_gate2_queue.py) — table/th/td/.badge/color classes above
   are already shared with that module's own CSS, so only its queue-specific classes are added here. */
.banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px}
.banner b{color:#1a5a92}
.batch-status{display:flex;justify-content:space-between;align-items:center;background:#f5f4f0;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:13px}
.batch-status form{margin:0}
button{background:#378ADD;color:#fff;border:none;border-radius:6px;padding:7px 14px;font-size:12px;cursor:pointer}
button:hover{background:#2c6fb3}
.rollups{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:24px}
.rollup{border-radius:8px;padding:12px 14px;font-size:12px;line-height:1.6}
.rollup.ok{background:#eaf3de;border:1px solid #a8d18d}
.rollup.over{background:#fdf2f2;border:1px solid #f0c9c9}
.rollup .region{font-weight:600;font-size:13px;margin-bottom:4px}
.rollup.ok .region{color:#3b6d11}
.rollup.over .region{color:#a32d2d}
.override-form{display:flex;gap:4px;margin-top:6px}
.override-form input{font-size:11px;border:1px solid #ddd;border-radius:4px;padding:3px 6px;width:140px}
.override-form button{padding:3px 8px;font-size:11px;background:#ef9f27}
.override-form button:hover{background:#d98a1a}
.empty{color:#888;font-size:13px;padding:20px;text-align:center}
"""

# Ordinal ranking so ascending sort reads green -> yellow -> red -> in-review, the same order the
# risk-mix legend already uses, rather than an arbitrary alphabetical badge-text sort.
_INDICATOR_RANK = {"green": 0, "yellow": 1, "red": 2}


def _bar_row(label, count, total, color):
    pct = round(100 * count / total) if total else 0
    return (f'<div class="drow"><div class="dlabel"><span>{label}</span><span>{count} ({pct}%)</span></div>'
            f'<div class="dbar"><div class="dbar-fill" style="width:{pct}%;background:{color}"></div></div></div>')


def _bar_row_usd(label, value, total_value, color):
    """Same bar, but the right-hand figure is a real dollar amount (e.g. Portfolio Value by Business
    Unit) instead of a row count — _bar_row's count display would be misleading for a sum-of-money
    metric."""
    pct = round(100 * value / total_value) if total_value else 0
    return (f'<div class="drow"><div class="dlabel"><span>{label}</span><span>${value/1000:.0f}K ({pct}%)</span></div>'
            f'<div class="dbar"><div class="dbar-fill" style="width:{pct}%;background:{color}"></div></div></div>')


def render():
    conn = get_connection()

    # --- whole-portfolio numbers (unfiltered — every row, every status, no LIMIT) ---
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM projects").fetchall()]
    total_projects = len(all_rows)

    APPROVED_STATUSES = ("accepted", "in_progress", "completed")
    PENDING_STATUSES = ("draft", "pmo_review", "analysis")
    approved_rows = [r for r in all_rows if r["status"] in APPROVED_STATUSES]
    pending_rows = [r for r in all_rows if r["status"] in PENDING_STATUSES]
    rejected_rows = [r for r in all_rows if r["status"] == "rejected"]
    # Cancelled is deliberately its own bucket, not folded into "rejected" — a cancelled project was
    # accepted, then stopped later (typically PMO acting on a post-acceptance update revealing it's
    # slipping badly, §7.2/Gate 3's Cancel decision), which is real information distinct from a
    # proposal that was never approved in the first place.
    cancelled_rows = [r for r in all_rows if r["status"] == "cancelled"]

    # Approved rate is computed over DECIDED intake proposals only (approved + rejected) —
    # draft/pmo_review/analysis rows haven't reached a decision yet, and cancelled projects WERE
    # approved at intake (this metric is about the intake decision, not later lifecycle outcome), so
    # neither belongs in this specific denominator.
    decided_count = len(approved_rows) + len(cancelled_rows) + len(rejected_rows)
    approved_rate = round(100 * (len(approved_rows) + len(cancelled_rows)) / decided_count) if decided_count else None

    # Portfolio value — same rows/definition as the original single "Portfolio value" card: projects
    # genuinely in the pipeline (accepted through analysis), not draft/rejected/cancelled ones whose
    # business_impact was never realized (or, for cancelled, no longer being realized). Renamed from
    # a generic "cost savings" framing to what this number actually is.
    pipeline_rows = [r for r in all_rows if r["status"] in ("accepted", "in_progress", "completed", "pmo_review", "analysis")]
    portfolio_value = sum(r["business_impact_usd"] or 0 for r in pipeline_rows)

    # --- Agent 10 (§7) predictions — only tracked (accepted/in_progress/completed) rows are
    # eligible at all; predict_or_monitor() applies the age gate itself. ---
    for r in all_rows:
        if r["status"] in APPROVED_STATUSES:
            pred = predict_or_monitor(r)
            r["_pred_status"] = pred["status"]
            r["_pred_score"] = pred["success_score"]
        else:
            r["_pred_status"] = "not_tracked"
            r["_pred_score"] = None
    scores = [r["_pred_score"] for r in all_rows if r["_pred_status"] == "predicted"]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    # --- Predictive Portfolio Health — Agent 10's real per-project prediction (_pred_status/
    # _pred_score, just computed above), bucketed instead of only averaged. The single "Avg success
    # likelihood" metric card can hide a bimodal spread (a handful of very low scores balanced out by
    # high ones averaging to something reassuring) — a PMO scanning for risk needs the buckets, not
    # just the mean. ---
    health_counts = {"high": 0, "medium": 0, "low": 0, "under_monitoring": 0, "not_tracked": 0}
    for r in all_rows:
        if r["_pred_status"] == "predicted":
            score = r["_pred_score"] or 0
            if score >= 70:
                health_counts["high"] += 1
            elif score >= 40:
                health_counts["medium"] += 1
            else:
                health_counts["low"] += 1
        elif r["_pred_status"] == "under_monitoring":
            health_counts["under_monitoring"] += 1
        else:
            health_counts["not_tracked"] += 1

    # --- Portfolio Value by Business Unit — real business_impact_usd summed per BU across the same
    # pipeline_rows scope as the "Portfolio value" metric card, so a PMO can see WHERE that total is
    # concentrated (concentration risk), not just the single aggregate figure. ---
    bu_totals = {}
    for r in pipeline_rows:
        bu = r["business_unit"] or "Unspecified"
        bu_totals[bu] = bu_totals.get(bu, 0) + (r["business_impact_usd"] or 0)
    bu_ranked = sorted(bu_totals.items(), key=lambda kv: kv[1], reverse=True)

    # --- the "active" table view — accepted/in_progress/completed/pmo_review/analysis rows, ordered
    # by recency. No LIMIT: the trial fixture only has 20 rows total (see TECH-SPEC.md §14), so a
    # cap sized for the old 100-row era would silently start truncating again the moment the fixture
    # grows back past 20 — dropping it here costs nothing today and removes that latent bug. ---
    # Cancelled projects stay visible here (not silently dropped) — a PMO scanning the portfolio
    # should see what got stopped, tagged distinctly, not have it vanish from the list entirely.
    rows = [r for r in all_rows if r["status"] in ("accepted", "in_progress", "completed", "pmo_review", "analysis", "cancelled")]
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    active_count = len(rows)

    # CAPEX and risk-mix are about CURRENT exposure on still-active work — a cancelled project isn't
    # drawing budget or carrying risk anymore, so it's excluded from both even though it stays
    # visible in the table above.
    still_active_rows = [r for r in rows if r["status"] != "cancelled"]
    scored = [r for r in still_active_rows if r["risk_indicator"]]
    capex_needed = sum(r["capex_usd"] or 0 for r in scored)
    capex_funded = sum((r["capex_usd"] or 0) * (r["capex_funded_pct"] or 0) / 100 for r in scored)
    capex_pct = round(100 * capex_funded / capex_needed) if capex_needed else 0

    # --- CAPEX Funding Coverage — only rows that actually need CAPEX (capex_usd truthy) count here;
    # a project with no CAPEX need at all isn't "unfunded", it just doesn't belong in this metric.
    # Same still-active scope as the CAPEX-funded % heading above. ---
    capex_need_rows = [r for r in still_active_rows if r["capex_usd"]]
    fully_funded = sum(1 for r in capex_need_rows if (r["capex_funded_pct"] or 0) >= 100)
    unfunded = sum(1 for r in capex_need_rows if not r["capex_funded_pct"])
    partially_funded = len(capex_need_rows) - fully_funded - unfunded

    risk_counts = {"green": 0, "yellow": 0, "red": 0, "in_review": 0}
    for r in still_active_rows:
        if r["risk_indicator"] in risk_counts:
            risk_counts[r["risk_indicator"]] += 1
        else:
            risk_counts["in_review"] += 1

    # Needs-attention must never miss a red project just because it fell outside the "active" set
    # above — query it separately, unbounded, exactly as before.
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
        return r["project_id"] if r["project_id"] else "—"

    dashboard_dir = os.path.dirname(os.path.abspath(__file__))

    def name_cell(r):
        link_id = r["project_id"] or r["submission_id"]
        vis_path = os.path.join(dashboard_dir, f"visualizer_{link_id}.html")
        name_html = f'<b>{r["project_name"]}</b>'
        if os.path.isfile(vis_path):
            name_html = f'<a href="visualizer_{link_id}.html" style="color:#1a1a1a;text-decoration:none">{name_html}</a>'
        if r["status"] == "cancelled":
            name_html += ' <span class="badge gray">cancelled</span>'
        return name_html

    def rank(val):
        return _INDICATOR_RANK.get(val, 3)

    table_rows = "".join(
        f'<tr>'
        f'<td data-v="{(r["project_name"] or "").lower()}">{name_cell(r)}<br>'
        f'<span style="color:#378ADD;font-size:11px;font-family:monospace">{project_id_cell(r)}</span> · '
        f'<span style="color:#888;font-size:11px">{r["region"]} · {r["business_unit"]}</span></td>'
        f'<td data-v="{r["business_impact_usd"] or 0}" style="text-align:right">${(r["business_impact_usd"] or 0)/1000:.0f}K</td>'
        f'<td data-v="{rank(r["risk_indicator"])}">{badge(r["risk_indicator"])}</td>'
        f'<td data-v="{rank(r["schedule_status"])}">{badge(r["schedule_status"])}</td>'
        f'<td data-v="{rank(r["resource_indicator"])}">{badge(r["resource_indicator"])}</td>'
        f'<td data-v="{r["capex_funded_pct"] if r["capex_funded_pct"] is not None else -1}" style="text-align:right">{r["capex_funded_pct"] or "—"}{"%" if r["capex_funded_pct"] else ""}</td>'
        f'<td data-v="{r["_pred_score"] if r["_pred_score"] is not None else -1}" style="text-align:right">{score_cell(r)}</td>'
        f'</tr>'
        for r in rows
    )

    queue_fragment, queue_len = render_queue_fragment(conn)

    status_bars = (
        _bar_row("Approved / in progress", len(approved_rows), total_projects, "#5fd07a")
        + _bar_row("Pending review", len(pending_rows), total_projects, "#e8b34d")
        + _bar_row("Cancelled", len(cancelled_rows), total_projects, "#8fa3c7")
        + _bar_row("Rejected", len(rejected_rows), total_projects, "#e2574f")
    )
    capex_coverage_bars = (
        _bar_row("Fully funded", fully_funded, len(capex_need_rows), "#5fd07a")
        + _bar_row("Partially funded", partially_funded, len(capex_need_rows), "#e8b34d")
        + _bar_row("Unfunded", unfunded, len(capex_need_rows), "#e2574f")
    ) if capex_need_rows else '<div style="font-size:12px;color:#93a8d0">No active projects currently need CAPEX.</div>'
    health_bars = (
        _bar_row("High (≥70)", health_counts["high"], total_projects, "#5fd07a")
        + _bar_row("Medium (40–69)", health_counts["medium"], total_projects, "#e8b34d")
        + _bar_row("Low (<40)", health_counts["low"], total_projects, "#e2574f")
        + _bar_row("Under monitoring", health_counts["under_monitoring"], total_projects, "#8fa3c7")
        + _bar_row("Not yet tracked", health_counts["not_tracked"], total_projects, "#3d4f78")
    )
    _BU_COLORS = ["#5fd07a", "#378ADD", "#e8b34d", "#e2574f", "#8fa3c7", "#c77dd1", "#3d4f78", "#e0894f"]
    bu_bars = "".join(
        _bar_row_usd(bu, val, portfolio_value, _BU_COLORS[i % len(_BU_COLORS)])
        for i, (bu, val) in enumerate(bu_ranked)
    ) if bu_ranked else '<div style="font-size:12px;color:#93a8d0">No active portfolio value yet.</div>'

    sortable_cols = ["Project", "Size of price", "Risk", "Schedule", "Resource", "CAPEX funded", "Score"]
    header_html = "".join(
        f'<th class="sortable" data-col="{i}">{label}<span class="arrow"></span></th>'
        for i, label in enumerate(sortable_cols)
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PMO Topline Dashboard</title><style>{CSS}</style></head>
<body>
<div class="nav"><a href="/" target="_top">← Composer</a><a href="activity.html">Portfolio activity feed</a><a href="#gate2review">Gate 2 review{f' ({queue_len} pending)' if queue_len else ''}</a></div>
<h2>PMO portfolio — topline</h2>

<div class="metrics">
<div class="mcard"><div class="mlabel">Total Projects</div><div class="mnum">{total_projects}</div></div>
<div class="mcard"><div class="mlabel">Portfolio value</div><div class="mnum">${portfolio_value/1e6:.2f}M</div></div>
<div class="mcard"><div class="mlabel">Approved rate</div><div class="mnum">{f"{approved_rate}%" if approved_rate is not None else "—"}</div></div>
<div class="mcard"><div class="mlabel">Avg success likelihood</div><div class="mnum">{avg_score}</div></div>
</div>

<div class="distros">
<div class="distro"><h4>Status Distribution</h4>{status_bars}</div>
<div class="distro"><h4>CAPEX Funding Coverage</h4>{capex_coverage_bars}</div>
<div class="distro"><h4>Predictive Portfolio Health</h4>{health_bars}</div>
<div class="distro"><h4>Portfolio Value by Business Unit</h4>{bu_bars}</div>
</div>

<div class="riskmix">
<span>Risk mix (active projects)</span>
<span><span class="dot" style="background:#639922"></span>{risk_counts['green']} green</span>
<span><span class="dot" style="background:#ef9f27"></span>{risk_counts['yellow']} yellow</span>
<span><span class="dot" style="background:#e24b4a"></span>{risk_counts['red']} red</span>
<span><span class="dot" style="background:#888"></span>{risk_counts['in_review']} in review</span>
</div>
{attention_html}

<h3 class="section-h" id="gate2review">Periodic Gate 2 Review (§5.3)</h3>
{queue_fragment}

<h3 class="section-h">Active projects ({active_count}) · CAPEX funded {capex_pct}%</h3>
<table id="ptable"><thead><tr>{header_html}</tr></thead><tbody>
{table_rows}
</tbody></table>

<script>
(function() {{
  var state = {{ col: null, dir: 1 }};
  var headers = document.querySelectorAll('#ptable th.sortable');
  headers.forEach(function(th) {{
    th.addEventListener('click', function() {{
      var col = parseInt(th.dataset.col, 10);
      state.dir = (state.col === col) ? -state.dir : 1;
      state.col = col;
      headers.forEach(function(h) {{ h.querySelector('.arrow').textContent = ''; }});
      th.querySelector('.arrow').textContent = state.dir === 1 ? '▲' : '▼';
      var tbody = document.querySelector('#ptable tbody');
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      rows.sort(function(a, b) {{
        var av = a.children[col].dataset.v, bv = b.children[col].dataset.v;
        var an = parseFloat(av), bn = parseFloat(bv);
        var cmp;
        if (!isNaN(an) && !isNaN(bn)) {{ cmp = an - bn; }}
        else {{ cmp = av < bv ? -1 : (av > bv ? 1 : 0); }}
        return cmp * state.dir;
      }});
      rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }});
  }});
}})();

// Case 8/9 (§7.2 change management) never run through the Live Execution Visualizer, which is
// normally what tells the composer's right panel a notification just fired — so scripts/
// demo_engine.py's _redirect_with_notification() carries the real notification Agent 12 wrote
// (auto-applied, Gate 3 authorized, or Gate 3 declined) here as a query string instead. Post it to
// the parent exactly like the visualizer does, so a PMO who just clicked Decline sees real
// confirmation that the decision was recorded, not just an unchanged table with no feedback at all.
(function() {{
  var params = new URLSearchParams(window.location.search);
  var subject = params.get('notif_subject');
  if (subject) {{
    try {{
      window.parent.postMessage({{type: 'notification', notif: {{
        trigger_label: params.get('notif_trigger') || 'Agent 12 · Change evaluator',
        subject: subject, body: params.get('notif_body') || '',
        recipient: params.get('notif_recipient') || 'Project team',
        channel: params.get('notif_channel') || 'email',
      }}}}, '*');
    }} catch (e) {{}}
    if (window.history && window.history.replaceState) {{
      window.history.replaceState({{}}, '', window.location.pathname + window.location.hash);
    }}
  }}
}})();
</script>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "topline.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, active_count

if __name__ == "__main__":
    path, count = render()
    print(f"rendered {path} with {count} projects")
