"""
§5.3 Periodic Gate 2 Review — the batch queue view. A natural extension of Agent 9 (Dashboard
Service, §2 — already "continuous... serves project list/filters"), not a new agent: every project
sitting at status='analysis' IS the queue (no separate queue table), grouped by region with a
portfolio-level rollup showing what the WHOLE queue is asking for against each region's CAPEX budget
(§5.2) — genuinely different math from Agent 5's per-project budget_flag, which can't see its
queue-mates. PMO reviews from here, not one project blind to the rest of the pending set.
"""
import sys, os, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import get_gate2_queue, get_regional_committed_capex, get_open_gate2_batch
from src.shared.config import REGIONAL_CAPEX_BUDGET_USD, BUDGET_HEADROOM_LENS_THRESHOLD, GATE2_FAST_TRACK_CAPEX_USD

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
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
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#5f5e5a;font-weight:400;font-size:11px;padding:8px 6px;border-bottom:1px solid #ddd}
td{padding:8px 6px;border-bottom:1px solid #eee;vertical-align:top}
.badge{font-size:11px;padding:2px 8px;border-radius:6px}
.green{background:#eaf3de;color:#3b6d11}.yellow{background:#faeeda;color:#854f0b}.red{background:#fcebeb;color:#a32d2d}.gray{background:#f1efe8;color:#5f5e5a}
.override-form{display:flex;gap:4px;margin-top:6px}
.override-form input{font-size:11px;border:1px solid #ddd;border-radius:4px;padding:3px 6px;width:140px}
.override-form button{padding:3px 8px;font-size:11px;background:#ef9f27}
.override-form button:hover{background:#d98a1a}
.empty{color:#888;font-size:13px;padding:20px;text-align:center}
"""


def _compute_region_rollups(conn, queue_rows):
    regions = sorted(set(r["region"] for r in queue_rows if r["region"]))
    rollups = {}
    for region in regions:
        budget = REGIONAL_CAPEX_BUDGET_USD.get(region)
        committed = get_regional_committed_capex(conn, region)
        queued_ask = sum((r["capex_usd"] or 0) for r in queue_rows if r["region"] == region)
        total_if_all_approved = committed + queued_ask
        if budget:
            headroom_before = max(budget - committed, 0)
            headroom_pct_before = round(headroom_before / budget, 3)
            lens = "low_risk_low_capex_first" if headroom_pct_before < BUDGET_HEADROOM_LENS_THRESHOLD else "best_roi_ratio_first"
            over = total_if_all_approved > budget
        else:
            headroom_pct_before, lens, over = None, None, False
        rollups[region] = {
            "budget_cap": budget, "committed": committed, "queued_ask": queued_ask,
            "total_if_all_approved": total_if_all_approved, "over_budget_if_all_approved": over,
            "headroom_pct_before": headroom_pct_before, "recommended_lens": lens,
        }
    return rollups


def _rollup_card(region, r):
    cls = "over" if r["over_budget_if_all_approved"] else "ok"
    lens_label = {
        "low_risk_low_capex_first": "low-risk / low-CAPEX first",
        "best_roi_ratio_first": "best ROI-ratio first",
    }.get(r["recommended_lens"], "—")
    budget_line = f"${r['budget_cap']:,.0f} budget" if r["budget_cap"] else "not in REGIONAL_CAPEX_BUDGET_USD table"
    over_note = "<br><b>⚠ Approving everything queued would exceed budget</b>" if r["over_budget_if_all_approved"] else ""
    return f"""<div class="rollup {cls}">
  <div class="region">{html_lib.escape(region)}</div>
  Committed: ${r['committed']:,.0f} · Queued asks: ${r['queued_ask']:,.0f}<br>
  If all approved: ${r['total_if_all_approved']:,.0f} of {budget_line}<br>
  Prioritization lens: <b>{lens_label}</b>{over_note}
</div>"""


def _badge(val):
    if not val:
        return '<span class="badge gray">—</span>'
    return f'<span class="badge {val}">{val}</span>'


def render():
    conn = get_connection()
    queue_rows = get_gate2_queue(conn)
    rollups = _compute_region_rollups(conn, queue_rows)
    open_batch = get_open_gate2_batch(conn)

    from src.db.repositories import get_latest_agent_payload
    rows_html = []
    for r in queue_rows:
        pid = r["project_id"] or r["submission_id"]
        a5 = get_latest_agent_payload(conn, pid, "agent5_business_impact") or {}
        a6 = get_latest_agent_payload(conn, pid, "agent6_knowledge_crosscheck") or {}
        fast_track_note = (
            f' <span class="badge green">fast-track eligible (&lt;${GATE2_FAST_TRACK_CAPEX_USD:,.0f})</span>'
            if (r["capex_usd"] or 0) < GATE2_FAST_TRACK_CAPEX_USD else ""
        )
        rows_html.append(f"""<tr>
  <td><b>{html_lib.escape(r['project_name'] or '')}</b><br>
  <span style="color:#888;font-size:11px">{html_lib.escape(r['region'] or '—')} · {html_lib.escape(r['business_unit'] or '—')}</span></td>
  <td style="text-align:right">${(r['capex_usd'] or 0):,.0f}</td>
  <td>{a5.get('margin_impact', '—')}</td>
  <td>{_badge(a6.get('verdict'))}</td>
  <td>
    <form method="POST" action="/queue/review/{r['submission_id']}" target="middle-frame" style="margin-bottom:6px">
      <button type="submit">Review &amp; decide</button>
    </form>
    <form method="POST" action="/queue/override/{r['submission_id']}" target="middle-frame" class="override-form">
      <input type="text" name="reason" placeholder="Override reason..." required>
      <button type="submit">Pull from queue</button>
    </form>
    {fast_track_note}
  </td>
</tr>""")

    batch_status_html = (
        f"""<div class="batch-status">
  <span>Batch <b>#{open_batch['id']}</b> open since {open_batch['opened_at']} (opened by {html_lib.escape(open_batch['opened_by'] or 'PMO')})</span>
  <form method="POST" action="/queue/close-batch/{open_batch['id']}" target="middle-frame"><button type="submit">Close this batch</button></form>
</div>"""
        if open_batch else
        """<div class="batch-status">
  <span>No batch currently open.</span>
  <form method="POST" action="/queue/open-batch" target="middle-frame"><button type="submit">Open this week's batch</button></form>
</div>"""
    )

    rollups_html = "".join(_rollup_card(region, r) for region, r in rollups.items()) or '<div class="empty">Nothing queued — no regional asks to roll up.</div>'
    table_html = (
        f'<table><tr><th>Project</th><th style="text-align:right">CAPEX</th><th>Agent 5</th><th>Agent 6</th><th>Actions</th></tr>{"".join(rows_html)}</table>'
        if rows_html else '<div class="empty">The Gate 2 queue is empty — nothing is currently sitting at Manual Gate 2.</div>'
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Gate 2 — Batch Queue</title>
<style>{CSS}</style></head><body>
<div class="nav"><a href="/dashboard/topline.html" target="_top">← Dashboard</a></div>
<div class="banner"><b>Periodic Gate 2 Review (§5.3).</b> Every project here has finished Agent 5/6
analysis and is waiting for a real Gate 2 decision — reviewed together, weekly by default, so a
region's budget is seen as one shared pool, not project-by-project blind spots. Sub-${GATE2_FAST_TRACK_CAPEX_USD:,.0f}
projects skip this queue automatically (playbook.md's existing fast-track tier); anything else can
still be pulled out early with a logged reason.</div>
{batch_status_html}
<h3 style="font-size:14px;margin-bottom:8px">Regional CAPEX rollup</h3>
<div class="rollups">{rollups_html}</div>
<h3 style="font-size:14px;margin-bottom:8px">Queued projects ({len(queue_rows)})</h3>
{table_html}
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "gate2_queue.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, len(queue_rows)


if __name__ == "__main__":
    path, count = render()
    print(f"rendered {path} with {count} queued projects")
