"""
Manual Gate 3 decision page (§7.2.2, §8.2 guardrail 3) — the real stop for a post-acceptance change
Agent 12 evaluated as 'needs_authorization' (regression on timeline/cost/risk, or no governance
axis actually improved). Agent 12 only ever proposes on this path; nothing applies to the live
`projects` row until a PMO presses Accept or Reject here.

Rendered as a standalone page filling the WHOLE middle panel (unlike Gate 2, which is squeezed into
the right panel so it never interrupts the flow-graph view, §9.3.4) — there's no flow graph running
underneath a Gate 3 decision, so no need for that cross-frame dance. Buttons submit via fetch() and
self-navigate on success, same JSON contract as Gate 2's /gate2/ route.
"""
import sys, os, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:680px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:13px}
.banner b{color:#1a5a92}
.summary{background:#f5f4f0;border-radius:8px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.7}
.diff{border:1px solid #e5e3dc;border-radius:8px;padding:14px 16px;margin-bottom:16px}
.diff table{width:100%;border-collapse:collapse;font-size:13px}
.diff th{text-align:left;color:#5f5e5a;font-weight:400;font-size:11px;padding:4px 6px;border-bottom:1px solid #ddd}
.diff td{padding:6px;border-bottom:1px solid #eee}
.diff .field{font-weight:600}
.diff .before{color:#a32d2d}
.diff .after{color:#3b6d11;font-weight:600}
.reason{border-left:3px solid #ef9f27;background:#faeeda;border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:20px;font-size:13px}
.decision{display:flex;gap:12px;margin-top:20px}
.decision button{flex:1;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}
.accept{background:#639922;color:#fff}
.accept:hover{background:#527d1c}
.reject{background:#e24b4a;color:#fff}
.reject:hover{background:#c53d3c}
.cancel{background:#5f5e5a;color:#fff}
.cancel:hover{background:#464540}
.comment-panel{margin-top:16px}
.comment-panel label{font-size:12px;font-weight:600;color:#5f5e5a;display:block;margin-bottom:4px}
.comment-panel textarea{width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:13px;font-family:inherit}
"""

_FIELD_LABELS = {
    "expected_launch_date": "Expected launch",
    "capex_usd": "CAPEX",
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


def render(change_request_id, project, update_entry, change_request):
    before_state = update_entry["before_state"]
    after_state = update_entry["after_state"]

    rows = "".join(
        f"""<tr><td class="field">{_FIELD_LABELS.get(f, f)}</td>
        <td class="before">{html_lib.escape(_fmt(f, before_state.get(f)))}</td>
        <td>→</td>
        <td class="after">{html_lib.escape(_fmt(f, after_state.get(f)))}</td></tr>"""
        for f in update_entry["fields_changed"]
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Gate 3 — PMO Authorization Needed</title>
<style>{CSS}</style></head><body>
<div class="banner"><b>Manual Gate 3 — a project update needs PMO authorization.</b> Agent 12 (§7.2.2)
evaluated this change against the project's current timeline/cost/risk and found it isn't a clean
improvement across the board. It's been captured, not applied — nothing changes on the live project
until you decide here.</div>
<div class="summary">
<b>{html_lib.escape(project['project_name'] or '')}</b> ({html_lib.escape(project['project_id'] or project['submission_id'])})<br>
Requested by: {html_lib.escape(update_entry.get('submitted_by') or 'Unknown')}<br>
Note: {html_lib.escape(update_entry.get('note') or '—')}
</div>
<div class="diff">
<table><tr><th>Field</th><th>Before</th><th></th><th>After</th></tr>
{rows}
</table>
</div>
<div class="reason"><b>Why this needs authorization:</b> {html_lib.escape(change_request.get('reason') or '')}</div>
<div class="decision">
  <button type="button" class="accept" id="accept-btn">✓ Authorize this change</button>
  <button type="button" class="reject" id="reject-btn">✗ Decline</button>
  <button type="button" class="cancel" id="cancel-btn">🛑 Cancel this project</button>
</div>
<div class="comment-panel">
  <label>PMO comment (optional — sent to the requester either way)</label>
  <textarea id="comment-field" rows="2" placeholder="e.g. reason for declining, conditions attached to authorizing, or why the project is being stopped..."></textarea>
</div>
<div id="gate3-status" style="font-size:12px;color:#888;margin-top:10px"></div>
<script>
var allButtons = ['accept-btn', 'reject-btn', 'cancel-btn'];
function submitDecision(decision) {{
  const statusEl = document.getElementById('gate3-status');
  allButtons.forEach(function(id) {{ document.getElementById(id).disabled = true; }});
  statusEl.innerText = decision === 'cancel' ? 'Cancelling the project…' : 'Submitting…';
  const body = new URLSearchParams();
  body.set('pmo_comment', document.getElementById('comment-field').value);
  fetch('/gate3/{change_request_id}/' + decision, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: body.toString(),
  }})
    .then(r => r.json().then(data => ({{ok: r.ok, data: data}})))
    .then(({{ok, data}}) => {{
      if (!ok || !data.redirect) {{ throw new Error(data.error || 'unexpected server response'); }}
      statusEl.innerText = 'Decision recorded — updating the dashboard…';
      window.location.href = data.redirect;
    }})
    .catch(err => {{
      statusEl.innerText = 'Something went wrong — ' + err;
      allButtons.forEach(function(id) {{ document.getElementById(id).disabled = false; }});
    }});
}}
document.getElementById('accept-btn').addEventListener('click', function() {{ submitDecision('accept'); }});
document.getElementById('reject-btn').addEventListener('click', function() {{ submitDecision('reject'); }});
document.getElementById('cancel-btn').addEventListener('click', function() {{
  if (confirm('Cancel this project entirely? This stops it — a bigger step than declining just this update.')) {{
    submitDecision('cancel');
  }}
}});
</script>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"gate3_{change_request_id}.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path

if __name__ == "__main__":
    print("This page is meant to be generated mid-flow by scripts/demo_server.py, not run standalone.")
