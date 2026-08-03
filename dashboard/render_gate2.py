"""
Manual Gate 2 decision page (§2, §8.2 guardrail 3) — the actual stop. Agent 6's output is never
allowed to auto-decide acceptance on its own; a PMO has to look at Agent 5 + Agent 6's findings and
press Accept or Reject.

Rendered small and embedded in the composer's RIGHT panel (scripts/demo_server.py), not the middle
one — the middle panel keeps showing the live execution graph the whole time, so making the actual
decision never interrupts a PMO's view of the flow. The two buttons submit via fetch() (not a normal
form POST) so this little iframe never navigates itself; instead it posts {type: 'decision_resolved',
redirect: ...} up to the parent composer once the server responds, and the parent is the one that
sends the middle panel on to replay the rest of the pipeline.
"""
import sys, os, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.orchestration.pipeline import default_gate2_rejection_reason

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:1rem;padding:0;color:#1a1a1a}
.banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:13px}
.banner b{color:#1a5a92}
.summary{background:#f5f4f0;border-radius:8px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.7}
.finding{border:1px solid #e5e3dc;border-radius:8px;padding:14px 16px;margin-bottom:12px}
.finding .who{font-size:12px;color:#5f5e5a;font-weight:600;margin-bottom:6px}
.finding .verdict{font-size:14px;font-weight:600;margin-bottom:4px}
.finding .citation{font-size:12px;color:#555;font-style:italic;border-left:2px solid #ddd;padding-left:10px;margin-top:6px}
.verdict.aligned, .verdict.positive{color:#3b6d11}
.verdict.misaligned{color:#a32d2d}
.verdict.partially_aligned, .verdict.unclear{color:#854f0b}
.accept-panel button, .reject-panel button{width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}
.accept{background:#639922;color:#fff}
.accept:hover{background:#527d1c}
.reject{background:#e24b4a;color:#fff}
.reject:hover{background:#c53d3c}
.hold{width:100%;border:none;border-radius:8px;background:#8a8778;color:#fff;padding:10px;font-size:13px;font-weight:600;cursor:pointer}
.hold:hover{background:#726f62}
.accept-panel{border:1px solid #cfe3b0;background:#f7fbf2;border-radius:8px;padding:14px 16px;margin-top:20px}
.reject-panel{border:1px solid #f0c9c9;background:#fff8f8;border-radius:8px;padding:14px 16px;margin-top:16px}
.accept-panel label, .reject-panel label{font-size:12px;font-weight:600;color:#5f5e5a;display:block;margin-bottom:4px}
.accept-panel textarea, .reject-panel textarea{width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:13px;font-family:inherit;margin-bottom:12px}
.reject-panel .hint{font-size:11px;color:#888;margin-top:-8px;margin-bottom:12px}
.hold-panel{border-top:1px dashed #ddd;margin-top:20px;padding-top:14px;text-align:center}
.hold-panel .hint{font-size:11px;color:#888;margin-bottom:8px}
.budget-flag{border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;line-height:1.6}
.budget-flag.ok{background:#f2f8ea;border:1px solid #c7e0a8}
.budget-flag.over{background:#fdf2f2;border:1px solid #f0c9c9}
.budget-flag .headline{font-weight:600;margin-bottom:2px}
.budget-flag.ok .headline{color:#3b6d11}
.budget-flag.over .headline{color:#a32d2d}
.similar-project{border-left:3px solid #378ADD;background:#e6f1fb;border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:16px;font-size:13px}
.similar-project b{color:#1a5a92}
.similar-project .excerpt{font-style:italic;color:#333;margin-top:4px}
"""

def _budget_flag_html(bf):
    """§5 playbook.md "Regional CAPEX Budgets" — Agent 5's deterministic (non-LLM) budget check.
    PMO sees this before deciding, same as the LLM findings below, but it's computed from real
    committed-CAPEX numbers, not model judgment. Informational only — never blocks Accept."""
    if not bf or bf.get("budget_cap") is None:
        return ""
    over = bf.get("over_budget")
    cls = "over" if over else "ok"
    headline = (
        f"⚠ Would push {bf['region']} over its CAPEX budget"
        if over else f"✓ Within {bf['region']}'s CAPEX budget"
    )
    lens_label = {
        "low_risk_low_capex_first": "low-risk / low-CAPEX projects first (headroom is tight)",
        "best_roi_ratio_first": "best ROI-ratio projects first (headroom is comfortable)",
    }.get(bf.get("recommended_lens"), bf.get("recommended_lens") or "—")
    return f"""<div class="budget-flag {cls}">
  <div class="headline">{headline}</div>
  Committed before this project: ${bf['committed_before']:,.0f} · After: ${bf['committed_after']:,.0f} of ${bf['budget_cap']:,.0f} budget
  ({bf['headroom_pct_before']*100:.0f}% headroom remaining before this project)<br>
  Per playbook.md's Portfolio Prioritization policy, this headroom level points to: <b>{lens_label}</b>
</div>"""


def render(submission_id, project, trace):
    a5 = trace.get("agent5", {})
    a6 = trace.get("agent6", {})
    can_accept = a6.get("verdict") in ("aligned", "partially_aligned")
    disabled_note = ""
    if not can_accept:
        disabled_note = ('<p style="font-size:12px;color:#a32d2d;margin-top:8px">Agent 6 verdict is '
                          "'misaligned' — Accept is disabled; this can only be rejected or sent back for review.</p>")
    proposed_reason = html_lib.escape(default_gate2_rejection_reason(a6))
    budget_flag_html = _budget_flag_html(a5.get("budget_flag"))
    spp = a5.get("similar_past_project")
    similar_project_html = ""
    if spp:
        similar_project_html = (
            f'<div class="similar-project"><b>Similar past project found:</b> '
            f'{html_lib.escape(spp["project_name"])} ({spp["similarity"]*100:.0f}% similar) — '
            f'this may be worth replicating.<div class="excerpt">"{html_lib.escape(spp["excerpt"])}"</div></div>'
        )
    team = getattr(project, "team_members", None) or []
    team_line = f"{', '.join(team)} ({len(team)} member{'s' if len(team) != 1 else ''})" if team else "not provided"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Gate 2 — PMO Decision Needed</title>
<style>{CSS}</style></head><body>
<div class="banner"><b>Manual Gate 2 — waiting on a PMO decision.</b> Agents 5 and 6 have finished
their analysis. Nothing else runs (no acceptance, no notification, no project ID) until a PMO
reviews this and presses Accept or Reject below.</div>
<div class="summary">
<b>{project.project_name}</b><br>
Objective: {project.objective}<br>
Solution: {project.solution}<br>
Size of price: ${(project.business_impact_usd or 0):,.0f} · CAPEX: ${(project.capex_usd or 0):,.0f}<br>
Expected launch: {getattr(project, "expected_launch_date", None) or "not provided"}<br>
Team assigned: {team_line} — staffing determined at intake; once accepted, ongoing team/resource
availability is tracked the same way as risk and schedule
</div>
{budget_flag_html}
{similar_project_html}
<div class="finding">
  <div class="who">Agent 5 · Business Impact Analyzer</div>
  <div class="verdict {a5.get('margin_impact','')}">Margin impact: {a5.get('margin_impact', '—')}</div>
  <div class="citation">"{a5.get('citation', '—')}"</div>
</div>
<div class="finding">
  <div class="who">Agent 6 · Knowledge Cross-Checker</div>
  <div class="verdict {a6.get('verdict','')}">Verdict: {a6.get('verdict', '—')}</div>
  <div class="citation">"{a6.get('citation', '—')}"</div>
</div>
<div class="accept-panel">
  <label>PMO comment (optional — included in the acceptance notification, e.g. praise or a watch-out to track post-acceptance)</label>
  <textarea id="accept-comment-field" rows="2" placeholder="e.g. great margin story here; keep an eye on the Q3 staffing dependency..."></textarea>
  <button type="button" class="accept" id="accept-btn" {'disabled' if not can_accept else ''}>✓ Accept</button>
</div>
{disabled_note}
<div class="reject-panel">
  <label>Reason for rejection (Agent 8's proposed reason — edit if you want something different)</label>
  <textarea id="reason-field" rows="2">{proposed_reason}</textarea>
  <label>Additional PMO comment (optional — added on top of the reason above, not a replacement)</label>
  <textarea id="comment-field" rows="2" placeholder="e.g. specific concerns, conditions for resubmission..."></textarea>
  <div class="hint">Leave the reason field as-is to send it exactly as Agent 8 proposed, or edit it to send something different.</div>
  <button type="button" class="reject" id="reject-btn">✗ Reject with this reason</button>
</div>
<div class="hold-panel">
  <div class="hint">Not ready to decide right now? Hold this for the next weekly Gate 2 batch instead —
  it stays exactly where it is and shows up on the <a href="/dashboard/gate2_queue.html" target="_top">Gate 2 queue</a> for review later.</div>
  <button type="button" class="hold" id="hold-btn">⏸ Hold for weekly batch</button>
</div>
<div id="gate2-status" style="font-size:12px;color:#888;margin-top:10px"></div>
<script>
function submitDecision(decision) {{
  const statusEl = document.getElementById('gate2-status');
  document.getElementById('accept-btn').disabled = true;
  document.getElementById('reject-btn').disabled = true;
  document.getElementById('hold-btn').disabled = true;
  statusEl.innerText = 'Submitting…';
  const body = new URLSearchParams();
  if (decision === 'accept') {{
    body.set('pmo_comment', document.getElementById('accept-comment-field').value);
  }}
  if (decision === 'reject') {{
    body.set('reason', document.getElementById('reason-field').value);
    body.set('pmo_comment', document.getElementById('comment-field').value);
  }}
  fetch('/gate2/{submission_id}/' + decision, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: body.toString(),
  }})
    .then(r => r.json().then(data => ({{ok: r.ok, data: data}})))
    .then(({{ok, data}}) => {{
      if (!ok || !data.redirect) {{ throw new Error(data.error || 'unexpected server response'); }}
      statusEl.innerText = decision === 'hold' ? 'Held — opening the Gate 2 queue…' : 'Decision recorded — updating the flow…';
      // This little iframe never navigates itself; the parent composer (scripts/demo_server.py)
      // is the one that sends the middle panel's flow graph on to replay the rest of the pipeline
      // (or, for a hold, over to the Gate 2 queue page).
      try {{ window.parent.postMessage({{type: 'decision_resolved', redirect: data.redirect}}, '*'); }} catch (e) {{}}
    }})
    .catch(err => {{
      statusEl.innerText = 'Something went wrong — ' + err;
      document.getElementById('accept-btn').disabled = false;
      document.getElementById('reject-btn').disabled = false;
      document.getElementById('hold-btn').disabled = false;
    }});
}}
document.getElementById('accept-btn').addEventListener('click', function() {{ submitDecision('accept'); }});
document.getElementById('reject-btn').addEventListener('click', function() {{ submitDecision('reject'); }});
document.getElementById('hold-btn').addEventListener('click', function() {{ submitDecision('hold'); }});
</script>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"gate2_{submission_id}.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path

if __name__ == "__main__":
    print("This page is meant to be generated by scripts/demo_server.py mid-flow, not run standalone.")
