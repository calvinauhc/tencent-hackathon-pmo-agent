"""
Agent 11 + 12 auto-apply confirmation page (§7.2.1 favorable path).

Rendered when Agent 12 evaluates a change as 'favorable' and immediately applies it — no Gate 3
needed. This replaces the old /dashboard/gate2_queue.html redirect (which showed nothing relevant)
with a clear summary of:
  • What Agent 11 captured (before → after diff)
  • What Agent 12 decided (favorable, reason)
  • The notification that was sent

Generated mid-flow by scripts/demo_engine.py's submit_project_update() (and the freeform variant),
then served as /dashboard/change_result_<project_id>.html.
"""
import sys, os, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSS = """
:root {
  --blue:      #2563eb; --blue-dark:#1d4ed8; --blue-light:#eff6ff; --blue-mid:#bfdbfe;
  --surface:   #ffffff; --surface-2:#f8fafc; --surface-3:#f1f5f9;
  --border:    #e2e8f0; --border-2: #cbd5e1;
  --text:      #0f172a; --text-2:   #475569; --text-3:   #94a3b8;
  --green-bg:  #f0fdf4; --green-bd: #86efac; --green-tx: #15803d;
  --yellow-bg: #fffbeb; --yellow-bd:#fcd34d; --yellow-tx:#92400e;
  --red-bg:    #fef2f2; --red-bd:   #fca5a5; --red-tx:   #b91c1c;
  --gray-bg:   #f8fafc; --gray-bd:  #cbd5e1; --gray-tx:  #475569;
  --radius:8px; --radius-lg:12px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.05);
  --shadow:    0 4px 6px -1px rgba(0,0,0,.08),0 2px 4px -2px rgba(0,0,0,.05);
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       max-width: 720px; margin: 2rem auto; padding: 0 1.5rem;
       color: var(--text); font-size: 13px; background: var(--surface-2); }
.nav { font-size: 12px; margin-bottom: 20px; display: flex; align-items: center; gap: 6px; }
.nav a { color: var(--blue); text-decoration: none; font-weight: 500; }
.nav a:hover { text-decoration: underline; }

/* Agent pipeline badge strip */
.pipeline { display: flex; align-items: center; gap: 0; margin-bottom: 24px; }
.agent-chip { background: var(--surface-3); border: 1px solid var(--border-2);
               border-radius: 20px; padding: 4px 12px; font-size: 11px; font-weight: 600;
               color: var(--text-2); white-space: nowrap; }
.agent-chip.active { background: var(--green-bg); border-color: var(--green-bd);
                      color: var(--green-tx); }
.arrow { color: var(--text-3); margin: 0 4px; font-size: 12px; }

/* Result banner */
.banner { background: var(--green-bg); border: 1px solid var(--green-bd);
          border-radius: var(--radius-lg); padding: 14px 18px; margin-bottom: 20px;
          display: flex; align-items: flex-start; gap: 12px; }
.banner-icon { font-size: 22px; line-height: 1; flex-shrink: 0; }
.banner-body { flex: 1; }
.banner-body .title { font-size: 14px; font-weight: 700; color: var(--green-tx); margin-bottom: 3px; }
.banner-body .subtitle { font-size: 12px; color: var(--text-2); line-height: 1.5; }

/* Project summary card */
.summary-card { background: var(--surface); border: 1px solid var(--border);
                border-radius: var(--radius-lg); padding: 14px 18px; margin-bottom: 16px;
                box-shadow: var(--shadow-sm); }
.summary-card .proj-name { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
.summary-card .meta { font-size: 12px; color: var(--text-2); line-height: 1.7; }
.summary-card .meta span { margin-right: 16px; }

/* Agent step cards */
.step-card { background: var(--surface); border: 1px solid var(--border);
              border-radius: var(--radius-lg); margin-bottom: 14px;
              box-shadow: var(--shadow-sm); overflow: hidden; }
.step-header { display: flex; align-items: center; gap: 10px;
               padding: 10px 16px; background: var(--surface-3);
               border-bottom: 1px solid var(--border); }
.step-badge { background: var(--blue); color: #fff; border-radius: 20px;
              padding: 2px 10px; font-size: 10.5px; font-weight: 700; letter-spacing: .02em;
              white-space: nowrap; }
.step-badge.green { background: var(--green-tx); }
.step-title { font-size: 13px; font-weight: 600; color: var(--text); }
.step-body { padding: 14px 18px; }

/* Diff table */
.diff-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.diff-table th { text-align: left; color: var(--text-3); font-weight: 600; font-size: 11px;
                  padding: 5px 8px; border-bottom: 2px solid var(--border);
                  text-transform: uppercase; letter-spacing: .04em; }
.diff-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.diff-table tr:last-child td { border-bottom: none; }
.diff-table .field-name { font-weight: 600; color: var(--text); }
.diff-table .before { color: var(--red-tx); text-decoration: line-through; opacity: .8; }
.diff-table .arrow-col { color: var(--text-3); padding: 0 4px; text-align: center; }
.diff-table .after { color: var(--green-tx); font-weight: 600; }

/* Reason pill */
.reason-box { background: var(--green-bg); border: 1px solid var(--green-bd);
               border-radius: var(--radius); padding: 10px 14px; font-size: 12px;
               color: var(--green-tx); line-height: 1.5; }
.reason-box b { font-weight: 700; }

/* Notification preview */
.notif-preview { background: var(--blue-light); border: 1px solid var(--blue-mid);
                  border-radius: var(--radius); padding: 12px 16px; font-size: 12px;
                  line-height: 1.6; }
.notif-preview .nfield { color: var(--text-3); font-size: 11px; font-weight: 600;
                           text-transform: uppercase; letter-spacing: .04em; }
.notif-preview .nval { color: var(--text); margin-bottom: 8px; }
.notif-preview .nbody-text { white-space: pre-wrap; color: var(--text-2);
                               border-top: 1px solid var(--blue-mid); padding-top: 10px;
                               margin-top: 4px; }
"""

_FIELD_LABELS = {
    "expected_launch_date": "Expected launch",
    "capex_usd": "CAPEX ($)",
    "risk_indicator": "Risk indicator",
    "schedule_status": "Schedule status",
    "resource_indicator": "Resource indicator",
}


def _fmt(field, val):
    if val is None:
        return "—"
    if field == "capex_usd":
        return f"${val:,.0f}"
    return str(val)


def render(project, update_entry, result):
    """
    project      — DB row dict for the updated project
    update_entry — dict from agent11_update_logger.log_update()
    result       — dict from agent12_change_evaluator.process_update()  (applied=True path)
    """
    project_id = project.get("project_id") or project.get("submission_id", "")
    project_name = project.get("project_name") or project_id
    submitted_by = update_entry.get("submitted_by") or "Unknown"
    note = update_entry.get("note") or "—"
    fields_changed = update_entry.get("fields_changed") or []
    before_state = update_entry.get("before_state") or {}
    after_state = update_entry.get("after_state") or {}
    reason = result.get("reason") or "All changed governance axes improved."
    notif = result.get("notification") or {}

    diff_rows = "".join(
        f"""<tr>
          <td class="field-name">{html_lib.escape(_FIELD_LABELS.get(f, f))}</td>
          <td class="before">{html_lib.escape(_fmt(f, before_state.get(f)))}</td>
          <td class="arrow-col">&#8594;</td>
          <td class="after">{html_lib.escape(_fmt(f, after_state.get(f)))}</td>
        </tr>"""
        for f in fields_changed
    ) or f'<tr><td colspan="4" style="color:var(--text-3);font-style:italic;padding:10px 8px">No field changes recorded.</td></tr>'

    notif_html = ""
    if notif:
        notif_html = f"""
        <div class="step-body">
          <div class="notif-preview">
            <div class="nfield">To</div>
            <div class="nval">{html_lib.escape(notif.get('recipient', 'PMO Team'))}</div>
            <div class="nfield">Subject</div>
            <div class="nval">{html_lib.escape(notif.get('subject', ''))}</div>
            <div class="nbody-text">{html_lib.escape(notif.get('body', ''))}</div>
          </div>
        </div>"""

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Change Applied — {html_lib.escape(project_name)}</title>
<style>{CSS}</style></head><body>

<div class="nav">
  <span style="color:var(--text-3)">&#8592;</span>
  <a href="/" target="_top">Composer</a>
</div>

<!-- Agent pipeline strip -->
<div class="pipeline">
  <div class="agent-chip active">Agent 11 &mdash; Update Logger</div>
  <span class="arrow">&#8594;</span>
  <div class="agent-chip active">Agent 12 &mdash; Change Evaluator</div>
  <span class="arrow">&#8594;</span>
  <div class="agent-chip active">Auto-applied &#10003;</div>
</div>

<!-- Result banner -->
<div class="banner">
  <div class="banner-icon">&#10003;</div>
  <div class="banner-body">
    <div class="title">Change automatically applied</div>
    <div class="subtitle">Agent 12 evaluated this update as <strong>favorable</strong> — all changed
    governance axes improved. No PMO authorization was required; the project record has been
    updated immediately.</div>
  </div>
</div>

<!-- Project summary -->
<div class="summary-card">
  <div class="proj-name">{html_lib.escape(project_name)}</div>
  <div class="meta">
    <span><strong>ID</strong> {html_lib.escape(project_id)}</span>
    <span><strong>Submitted by</strong> {html_lib.escape(submitted_by)}</span>
    <span><strong>Note</strong> {html_lib.escape(note)}</span>
  </div>
</div>

<!-- Agent 11 — captured diff -->
<div class="step-card">
  <div class="step-header">
    <span class="step-badge">Agent 11</span>
    <span class="step-title">Update Logger &mdash; captured change</span>
  </div>
  <div class="step-body">
    <table class="diff-table">
      <tr><th>Field</th><th>Before</th><th></th><th>After</th></tr>
      {diff_rows}
    </table>
  </div>
</div>

<!-- Agent 12 — evaluation -->
<div class="step-card">
  <div class="step-header">
    <span class="step-badge green">Agent 12</span>
    <span class="step-title">Change Evaluator &mdash; verdict: favorable</span>
  </div>
  <div class="step-body">
    <div class="reason-box"><b>Why it was auto-applied:</b> {html_lib.escape(reason)}</div>
  </div>
</div>

<!-- Notification sent -->
{f'<div class="step-card"><div class="step-header"><span class="step-badge" style="background:var(--text-2)">Notification</span><span class="step-title">Sent to PMO Team</span></div>{notif_html}</div>' if notif else ""}

</body></html>"""

    safe_id = project_id.replace("/", "_")
    out_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), f"change_result_{safe_id}.html")
    )
    with open(out_path, "w") as f:
        f.write(html_out)
    return out_path


if __name__ == "__main__":
    print("This page is generated mid-flow by scripts/demo_engine.py, not run standalone.")
