"""
Active projects — live risk/schedule/resource status (§14 follow-up).

When the topline dashboard was removed at explicit user request (§14's composer restructure), its
metric cards/activity feed/comment panel went with it deliberately — but so did the one place a PMO
could see an accepted/in_progress project's CURRENT risk_indicator/schedule_status/resource_indicator
after an update was applied. Agent 12's auto-apply and Gate 3-authorize paths both persist correctly
(src/db/repositories.py's apply_project_update()) — there was never a persistence bug — but nothing
rendered the result back. This fragment is that missing confirmation view, scoped deliberately small:
no metric cards, no distribution strip, just the live fields a PMO would check after "did my change
take effect."
"""
import sys, os, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import get_active_projects
from src.agents.agent10_success_predictor import predict_or_monitor

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
.banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px}
.banner b{color:#1a5a92}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#5f5e5a;font-weight:400;font-size:11px;padding:8px 6px;border-bottom:1px solid #ddd}
td{padding:8px 6px;border-bottom:1px solid #eee;vertical-align:top}
.badge{font-size:11px;padding:2px 8px;border-radius:6px}
.green{background:#eaf3de;color:#3b6d11}.yellow{background:#faeeda;color:#854f0b}.red{background:#fcebeb;color:#a32d2d}.gray{background:#f1efe8;color:#5f5e5a}
.empty{color:#888;font-size:13px;padding:20px;text-align:center}
.active-details summary{font-size:14px;font-weight:600;margin-bottom:8px;cursor:pointer;color:#1a1a1a;list-style-position:outside}
.active-details summary:hover{color:#378ADD}
.active-details table{margin-top:10px}
"""


def _badge(val):
    if not val:
        return '<span class="badge gray">—</span>'
    return f'<span class="badge {val}">{val}</span>'


def render_active_fragment(conn):
    """The actual content — banner + a table of every accepted/in_progress project's current
    risk/schedule/resource/CAPEX/success-score state, newest-updated first — as a standalone HTML
    fragment (no <html>/<body>/nav wrapper), same split as render_gate2_queue.render_queue_fragment()
    so both the standalone active_projects.html page and the composer's embedded copy render from
    exactly one computation. Returns (fragment_html, row_count)."""
    rows = get_active_projects(conn)

    rows_html = []
    for r in rows:
        pred = predict_or_monitor(r)
        score_cell = (
            f"{pred['success_score']}" if pred["status"] == "predicted" else "under monitoring"
        )
        rows_html.append(f"""<tr>
  <td><b>{html_lib.escape(r['project_name'] or '')}</b><br>
  <span style="color:#888;font-size:11px">{html_lib.escape(r['project_id'] or r['submission_id'])} · {html_lib.escape(r['region'] or '—')} · {html_lib.escape(r['business_unit'] or '—')}</span></td>
  <td>{_badge(r.get('status'))}</td>
  <td>{_badge(r.get('risk_indicator'))}</td>
  <td>{_badge(r.get('schedule_status'))}</td>
  <td>{_badge(r.get('resource_indicator'))}</td>
  <td style="text-align:right">{(r.get('capex_funded_pct') if r.get('capex_funded_pct') is not None else '—')}{'%' if r.get('capex_funded_pct') is not None else ''}</td>
  <td>{score_cell}</td>
  <td style="color:#888;font-size:11px">{html_lib.escape(str(r.get('updated_at') or '—'))}</td>
</tr>""")

    table_html = (
        f'<table><tr><th>Project</th><th>Status</th><th>Risk</th><th>Schedule</th>'
        f'<th>Resource</th><th style="text-align:right">CAPEX funded</th><th>Success score</th>'
        f'<th>Last updated</th></tr>{"".join(rows_html)}</table>'
        if rows_html else '<div class="empty">No accepted or in-progress projects right now.</div>'
    )
    # Same clutter-reduction pattern as the Gate 2 queue's table (§14 follow-up): collapsed by
    # default, one click away — this list only grows as more projects get accepted.
    section = (
        f"""<details class="active-details">
<summary>Active projects ({len(rows)})</summary>
{table_html}
</details>"""
        if rows_html else
        f"""<h3 style="font-size:14px;margin-bottom:8px">Active projects (0)</h3>
{table_html}"""
    )

    fragment = f"""<div class="banner"><b>Active projects — live status.</b> Every accepted or
in-progress project's current risk/schedule/resource state, straight from the database, sorted so
whichever project you (or Agent 12) just touched shows up first. This is where to look after
submitting a project update to confirm it actually applied — a schedule-only change auto-applies
immediately (Agent 12 doesn't treat schedule_status alone as governance-relevant), so it won't show
up as a notification or a Gate 3 review, only here.</div>
{section}"""
    return fragment, len(rows)


def render():
    """Standalone active_projects.html page — kept for direct linking/debugging, same role
    render_gate2_queue.render() plays for the queue; the primary PMO entry point is the embedded
    copy in the composer's left panel."""
    conn = get_connection()
    fragment, row_count = render_active_fragment(conn)
    out_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Active Projects</title>
<style>{CSS}</style></head><body>
<div class="nav"><a href="/" target="_top">← Composer</a></div>
{fragment}
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "active_projects.html"))
    with open(out_path, "w") as f:
        f.write(out_html)
    return out_path, row_count


if __name__ == "__main__":
    path, count = render()
    print(f"rendered {path} with {count} active projects")
