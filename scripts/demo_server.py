"""
In-browser demo composer (§0's simulated-intake decision, §12.1 entry point) — a local-only web
server (stdlib only, no new dependencies) with a three-panel layout:
  - Left:   the 7 named scenarios as predrafted "submission emails" (data/trial-projects.json's
            scenario_index, §12), each with a "Run this case" button.
  - Middle: an iframe showing whatever's happening — Gate 2 review if a PMO decision is needed, the
            live execution visualizer once it's resolved, or the topline dashboard by default.
  - Right:  a live notifications feed, PLUS the Gate 2 decision UI when one is needed. Notifications
            are not a static list — the visualizer in the middle panel posts a message the instant
            each notification's triggering step completes during replay, so a card appears here in
            sync with the graph, not before or after. When a run reaches Manual Gate 2, the decision
            form (Accept/Reject) opens here too, ABOVE the feed — never in the middle panel — so a
            PMO can make the call without losing sight of the flow graph they were just watching.
All three panels are drag-resizable (grab the thin divider between them) — widths persist in
localStorage across reloads.

Click "Run this case" and it triggers the real pipeline through Agents 1-6, with the middle panel
playing the live execution visualizer as it goes — so Agents 1,2,4,5,6 (+ Gate 1) actually run in
sequence on screen, not an instant jump. If the run reaches Manual Gate 2 (§2, §8.2 guardrail 3),
once that replay finishes the decision form opens in the RIGHT panel (a "Show Gate 2 decision now"
button in the middle panel skips ahead for anyone who doesn't want to wait) — the middle panel keeps
showing the completed graph the whole time. Nothing gets accepted, no project ID is issued, and no
notification goes out until a real PMO decision is made there. Rejecting lets the PMO edit or add to
Agent 8's proposed reason before it's sent. Once decided, the middle panel replays the rest of the
pipeline (Agent 7/9/10, or Agent 8) and the right panel's decision UI closes back to the notifications
feed. Scenarios that end before Gate 2 anyway (duplicate, incomplete, inconclusive) just replay
straight through with no decision step at all.

Usage:  python3 scripts/demo_server.py            (serves on http://127.0.0.1:8765)
Local-only by design (binds 127.0.0.1) — this is a demo tool for your own machine, not a deployment.
"""
import sys, os, html, json, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from demo_engine import (
    run_scenario_to_gate2, resume_scenario, SCENARIO_ORDER, SCENARIO_META, SCENARIO_EMAILS,
    submit_project_update, resolve_gate3_decision, CHANGE_DEMO_PAYLOADS, complete_project,
    run_batch_case, review_queued_project, override_queued_project, open_batch, close_batch,
    BATCH_CASE_META, render_gate2_queue, submit_freeform, FREEFORM_BODY_PLACEHOLDER,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD_DIR = os.path.join(REPO_ROOT, "dashboard")
PORT = 8765

# Submissions currently sitting at Manual Gate 2, waiting on a real PMO decision. Keyed by
# submission_id. This server is a single local process for one person's own demo session, so an
# in-memory dict is enough — no need for persistence across restarts.
PENDING = {}

# Once a Gate 2 decision has been made, remember the result. A refresh, a double-click, or the
# iframe re-submitting the form (browser back/forward) would otherwise hit a "no pending decision
# found" error even though the decision already went through — that reads as "nothing happened"
# even when it did. Redirecting to the same result instead makes the decision idempotent.
RESOLVED = {}

PAGE_CSS = """
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#1a1a1a}
#app{display:flex;height:100vh}
#left{width:360px;flex-shrink:0;overflow-y:auto;padding:1.25rem;background:#fafaf8}
#left h2{font-size:16px;margin:0 0 4px}
#left .sub{color:#5f5e5a;font-size:12px;margin-bottom:18px;line-height:1.5}
#middle{flex:1;display:flex;flex-direction:column;min-width:0}
#toolbar{display:flex;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid #e5e3dc;background:#fafaf8;flex-shrink:0}
#toolbar span{font-size:11px;color:#999;margin-right:4px}
#toolbar a{font-size:12px;color:#378ADD;text-decoration:none;padding:5px 10px;border-radius:6px;border:1px solid #dceafa}
#toolbar a:hover{background:#e6f1fb}
#middle iframe{flex:1;border:none;width:100%}
#right{width:340px;flex-shrink:0;background:#fafaf8;display:flex;flex-direction:column}
#right h3{font-size:13px;margin:0;padding:12px 14px;border-bottom:1px solid #e5e3dc;background:#fff}
.resizer{width:6px;flex-shrink:0;cursor:col-resize;background:#e5e3dc;position:relative;transition:background .15s}
.resizer:hover,.resizer.active{background:#378ADD}
.resizer::after{content:'';position:absolute;top:0;bottom:0;left:-3px;right:-3px}
#decision-area:empty{display:none}
#decision-area{flex-shrink:0;max-height:60vh;overflow-y:auto;border-bottom:3px solid #378ADD;background:#fff}
#decision-area iframe{width:100%;height:560px;border:none;display:block}
#notif-feed{flex:1;overflow-y:auto;padding:12px}
#notif-feed .empty{color:#999;font-size:12px;padding:8px 4px}
.notifcard{border:1px solid #e5e3dc;border-radius:8px;margin-bottom:10px;overflow:hidden;background:#fff;animation:pop .25s ease-out}
@keyframes pop {{ from {{ opacity:0; transform:translateY(-4px); }} to {{ opacity:1; transform:translateY(0); }} }}
.notifcard .nhead{font-size:10px;color:#378ADD;font-weight:600;background:#e6f1fb;padding:5px 10px}
.notifcard .nsubject{font-size:12px;font-weight:600;padding:8px 10px 0}
.notifcard .nbody{font-size:11px;color:#444;padding:4px 10px 10px;white-space:pre-wrap;line-height:1.5;max-height:120px;overflow-y:auto}
.notifcard .nto{font-size:10px;color:#888;padding:0 10px 6px}
.case{border:1px solid #e5e3dc;border-radius:10px;margin-bottom:12px;overflow:hidden;background:#fff}
.case .head{background:#f5f4f0;padding:10px 12px}
.case .head .title{font-weight:600;font-size:13px;display:block}
.case .head .outcome{font-size:11px;color:#5f5e5a;font-style:italic}
.mail{padding:10px 12px;font-size:12px;line-height:1.5;max-height:140px;overflow-y:auto}
.mail .line{margin-bottom:2px;color:#5f5e5a}
.mail .body{white-space:pre-wrap;margin-top:6px;color:#1a1a1a}
.runbar{padding:8px 12px;border-top:1px solid #eee;text-align:right}
button{background:#378ADD;color:#fff;border:none;border-radius:6px;padding:7px 14px;font-size:12px;cursor:pointer}
button:hover{background:#2c6fb3}
#action-select{width:100%;padding:8px 10px;font-size:13px;border:1px solid #e5e3dc;border-radius:6px;margin-bottom:12px;background:#fff}
.action-panel{display:none}
.action-panel.active{display:block}
.divider{display:flex;align-items:center;gap:10px;margin:20px 0 14px}
.divider .line{flex:1;height:1px;background:#e5e3dc}
.divider span{font-size:11px;color:#999}
#compose{border:1px solid #e5e3dc;border-radius:10px;padding:10px 12px;background:#fff}
#compose label{font-size:11px;color:#5f5e5a;display:block;margin-bottom:3px}
#compose input,#compose textarea{width:100%;font-size:12px;font-family:inherit;padding:6px 8px;border:1px solid #e5e3dc;border-radius:6px;margin-bottom:10px;box-sizing:border-box}
#compose textarea{height:120px;resize:vertical}
"""

def render_landing():
    options = []
    panels = []
    for i, key in enumerate(SCENARIO_ORDER, start=1):
        meta = SCENARIO_META[key]
        email = SCENARIO_EMAILS[key]
        options.append(f'<option value="{key}">Case {i} — {html.escape(meta["title"])}</option>')
        panels.append(f"""
<div class="action-panel{' active' if i == 1 else ''}" id="panel-{key}">
<div class="case">
  <div class="head"><span class="title">Case {i} — {html.escape(meta['title'])}</span>
  <span class="outcome">{html.escape(meta['outcome'])}</span></div>
  <div class="mail">
    <div class="line"><b>From:</b> {html.escape(email['from'])}</div>
    <div class="line"><b>Subject:</b> {html.escape(email['subject'])}</div>
    <div class="body">{html.escape(email['body'])}</div>
  </div>
  <form class="runbar" method="POST" action="/run/{key}" target="middle-frame">
    <button type="submit">▶ Run this case</button>
  </form>
</div>
</div>""")

    options.append('<option value="change">Change management (Agents 11/12)</option>')
    panels.append(f"""
<div class="action-panel" id="panel-change">
<div class="case" style="border-color:#dceafa">
  <div class="head" style="background:#e6f1fb"><span class="title">Post-acceptance change management (Agents 11/12)</span>
  <span class="outcome">Runs against Case 1's already-accepted project (PRJ-2026-0791)</span></div>
  <div class="mail" style="max-height:none">
    <div class="line">Simulates the project team submitting an ongoing status update. Agent 11 logs it;
    Agent 12 deterministically checks timeline/cost/risk and either applies it immediately or opens a
    real Manual Gate 3 for you to authorize.</div>
  </div>
  <div class="runbar" style="display:flex;gap:8px;justify-content:flex-end">
    <form method="POST" action="/change/PRJ-2026-0791/favorable" target="middle-frame">
      <button type="submit" style="background:#639922">✓ Simulate a favorable update</button>
    </form>
    <form method="POST" action="/change/PRJ-2026-0791/unfavorable" target="middle-frame">
      <button type="submit" style="background:#ef9f27">⚠ Simulate one needing PMO authorization</button>
    </form>
    <form method="POST" action="/complete/PRJ-2026-0791" target="middle-frame">
      <button type="submit" style="background:#5f5e5a">📄 Complete project → generate OPL (Agent 13)</button>
    </form>
  </div>
</div>
</div>""")

    options.append('<option value="batch">Periodic Gate 2 Review (§5.3)</option>')
    batch_buttons = "".join(
        f"""<form method="POST" action="/batch/{key}" target="middle-frame">
      <button type="submit">▶ {html.escape(BATCH_CASE_META[key]['title'])}</button>
    </form>"""
        for key in ("8a", "8b", "9", "10")
    )
    panels.append(f"""
<div class="action-panel" id="panel-batch">
<div class="case" style="border-color:#dceafa">
  <div class="head" style="background:#e6f1fb"><span class="title">Periodic Gate 2 Review (§5.3)</span>
  <span class="outcome">Weekly batch queue, budget rollup, fast-track + override exceptions</span></div>
  <div class="mail" style="max-height:none">
    <div class="line">Cases 8a/8b land in the same queue, competing for Southeast Asia's CAPEX budget.
    Case 9 (under $50K) skips the queue automatically. Case 10 waits in the queue until pulled out
    with a logged override reason. Open <a href="/dashboard/gate2_queue.html" target="middle-frame">the
    queue page</a> any time to see what's currently waiting.</div>
  </div>
  <div class="runbar" style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
    {batch_buttons}
  </div>
</div>
</div>""")

    compose_section = f"""
<div class="divider"><div class="line"></div><span>or submit your own</span><div class="line"></div></div>
<div id="compose">
  <form method="POST" action="/submit" target="middle-frame">
    <label for="c-from">From</label>
    <input id="c-from" name="from" type="text" placeholder="name@company.com" />
    <label for="c-subject">Subject</label>
    <input id="c-subject" name="subject" type="text" placeholder="Proposal — project name" />
    <label for="c-body">Body</label>
    <textarea id="c-body" name="body" placeholder="{html.escape(FREEFORM_BODY_PLACEHOLDER)}"></textarea>
    <div class="runbar" style="padding:0;border-top:none">
      <button type="submit">✉ Submit for review</button>
    </div>
  </form>
</div>
<div class="sub" style="margin-top:8px">Runs through the real pipeline — Agent 1 parses whatever's
typed (deterministic fallback in demo mode, so it works best matching the placeholder's shape), Agent
2 checks it against the real 100 trial projects for duplicates. Agent 5/6 use one generic mock
response in demo mode (no ANTHROPIC_API_KEY); set that env var and they judge it for real too.</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PMO Intake — Composer</title>
<style>{PAGE_CSS}</style></head><body>
<div id="app">
  <div id="left">
    <h2>PMO Project Intake — composer</h2>
    <div class="sub">Choose a case, or compose your own below, then run it through the real agent
    pipeline. Middle panel shows the flow — Gate 2 review if a PMO decision is needed, then the live
    execution graph. Right panel fills in with each notification the instant its step fires during
    replay.</div>
    <select id="action-select">{"".join(options)}</select>
    {"".join(panels)}
    {compose_section}
  </div>
  <div class="resizer" id="resize-left" title="Drag to resize"></div>
  <div id="middle">
    <div id="toolbar">
      <span>Jump to:</span>
      <a href="/dashboard/topline.html" target="middle-frame">🏠 Portfolio Dashboard</a>
      <a href="/dashboard/activity.html" target="middle-frame">📋 Activity Feed</a>
      <a href="/dashboard/gate2_queue.html" target="middle-frame">🗂 Gate 2 Queue</a>
    </div>
    <iframe name="middle-frame" id="middle-frame" src="/dashboard/topline.html"></iframe>
  </div>
  <div class="resizer" id="resize-right" title="Drag to resize"></div>
  <div id="right">
    <h3>📧 Notifications</h3>
    <div id="decision-area"></div>
    <div id="notif-feed"><div class="empty">Nothing sent yet — run a case and this fills in as the flow reaches each notification step.</div></div>
  </div>
</div>
<script>
function clearFeed() {{
  document.getElementById('notif-feed').innerHTML =
    '<div class="empty">Nothing sent yet — run a case and this fills in as the flow reaches each notification step.</div>';
}}
function addNotif(n) {{
  const feed = document.getElementById('notif-feed');
  const empty = feed.querySelector('.empty');
  if (empty) empty.remove();
  const card = document.createElement('div');
  card.className = 'notifcard';
  card.innerHTML =
    '<div class="nhead">Sent when: ' + n.trigger_label + '</div>' +
    '<div class="nsubject">' + n.subject + '</div>' +
    '<div class="nbody">' + n.body + '</div>' +
    '<div class="nto">To: ' + n.recipient + ' \\u00b7 ' + n.channel + '</div>';
  feed.appendChild(card);
  card.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
}}
function showDecision(url) {{
  document.getElementById('decision-area').innerHTML = '<iframe src="' + url + '"></iframe>';
}}
function clearDecision() {{
  document.getElementById('decision-area').innerHTML = '';
}}
window.addEventListener('message', function(e) {{
  if (!e.data || !e.data.type) return;
  if (e.data.type === 'reset') clearFeed();
  if (e.data.type === 'notification') addNotif(e.data.notif);
  if (e.data.type === 'gate2_pending') showDecision(e.data.gate2_url);
  if (e.data.type === 'decision_resolved') {{
    clearDecision();
    // The right panel's tiny decision iframe never navigates itself — the middle panel (the real
    // flow graph) is what continues on to replay the rest of the pipeline once a decision is made.
    document.getElementById('middle-frame').src = e.data.redirect;
  }}
}});
document.getElementById('middle-frame').addEventListener('load', function() {{ clearFeed(); clearDecision(); }});

// Draggable panel resizing — left/right panels remember their width in localStorage (this is a
// real local page in a real browser, not a sandboxed artifact preview, so persisting the layout
// across reloads is safe and just a convenience). Middle panel always fills whatever's left via
// flex:1, so only left/right need explicit widths.
(function() {{
  const leftPanel = document.getElementById('left');
  const rightPanel = document.getElementById('right');
  const savedLeft = localStorage.getItem('pmo_composer_left_width');
  const savedRight = localStorage.getItem('pmo_composer_right_width');
  if (savedLeft) leftPanel.style.width = savedLeft + 'px';
  if (savedRight) rightPanel.style.width = savedRight + 'px';

  function makeResizable(handle, panel, side, storageKey, minWidth, maxWidth) {{
    handle.addEventListener('mousedown', function(e) {{
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = panel.getBoundingClientRect().width;
      handle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      function onMove(e) {{
        let delta = e.clientX - startX;
        if (side === 'right') delta = -delta;
        let w = Math.round(startWidth + delta);
        w = Math.max(minWidth, Math.min(maxWidth, w));
        panel.style.width = w + 'px';
        localStorage.setItem(storageKey, w);
      }}
      function onUp() {{
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }}
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }});
  }}
  makeResizable(document.getElementById('resize-left'), leftPanel, 'left', 'pmo_composer_left_width', 240, 720);
  makeResizable(document.getElementById('resize-right'), rightPanel, 'right', 'pmo_composer_right_width', 240, 720);
}})();

// Dropdown swaps which panel is visible — purely client-side, every underlying form/route below
// is untouched, so this is just a view toggle over the exact same actions that used to be all
// stacked and always visible.
document.getElementById('action-select').addEventListener('change', function(e) {{
  document.querySelectorAll('.action-panel').forEach(function(p) {{ p.classList.remove('active'); }});
  var panel = document.getElementById('panel-' + e.target.value);
  if (panel) panel.classList.add('active');
}});
</script>
</body></html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep terminal quiet during a live demo

    def _no_cache(self):
        # Filenames like visualizer_PRJ-2026-0791.html and gate2_SUB-0001.html are REUSED across
        # every run of the same scenario (several trial-data anchors have a fixed, deterministic
        # project_id) — the same URL path, freshly regenerated content each time. Without this, a
        # browser can legitimately serve a stale cached copy of an old run's page (e.g. an old
        # Gate 2 decision that's already been resolved, or an old sequence/redirect_to), which reads
        # as a broken "decision not found" even though the current run is fine server-side.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")

    def _send_html(self, body, status=200):
        b = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self._no_cache()
        self.end_headers()
        self.wfile.write(b)

    def _send_json(self, obj, status=200):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self._no_cache()
        self.end_headers()
        self.wfile.write(b)

    def _read_form_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = urllib.parse.parse_qs(raw.decode("utf-8"))
        return {k: v[0] for k, v in parsed.items()}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "":
            self._send_html(render_landing())
            return
        if parsed.path.startswith("/dashboard/"):
            rel = urllib.parse.unquote(parsed.path[len("/dashboard/"):])
            full = os.path.normpath(os.path.join(DASHBOARD_DIR, rel))
            if not full.startswith(DASHBOARD_DIR) or not os.path.isfile(full):
                self._send_html("<h3>Not found</h3><p><a href='/' target='_top'>Back to composer</a></p>", 404)
                return
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._no_cache()
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_html("<h3>Not found</h3><p><a href='/' target='_top'>Back to composer</a></p>", 404)

    def _redirect(self, path):
        self.send_response(302)
        self.send_header("Location", path)
        self._no_cache()
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path.startswith("/run/"):
            key = parsed.path[len("/run/"):]
            if key not in SCENARIO_ORDER:
                self._send_html(f"<h3>Unknown scenario '{html.escape(key)}'</h3><p><a href='/' target='_top'>Back</a></p>", 404)
                return
            result = run_scenario_to_gate2(key)
            if result["status"] == "pending_gate2":
                # Real stop: don't run Agent 7-10 (or Agent 8) until a PMO actually decides. Land on
                # the visualizer FIRST so Agents 1,2,4,5,6 (+ Gate 1) actually play out in sequence —
                # it auto-forwards to the Gate 2 decision page once that replay finishes.
                # Several trial-data anchors (e.g. this one) have a fixed, deterministic
                # submission_id/project_id, so re-running the SAME case after already deciding it
                # once would otherwise leave a stale RESOLVED entry that silently short-circuits
                # this fresh decision with the OLD result — clear it, this is a brand new cycle.
                RESOLVED.pop(result["submission_id"], None)
                PENDING[result["submission_id"]] = {
                    "project": result["project"], "trace": result["trace"], "scenario_key": key,
                }
                self._redirect(f"/dashboard/visualizer_{result['visualizer_id']}.html")
            else:
                self._redirect(f"/dashboard/visualizer_{result['result_id']}.html")
            return

        if parsed.path == "/submit":
            # "Compose your own" (§12.1) — same PENDING/RESOLVED contract as /run/<key>, just
            # sourced from typed From/Subject/Body instead of a named scenario key. See
            # demo_engine.submit_freeform()'s docstring for what's genuinely live here (Agent 1
            # parse, Agent 2 duplicate check) versus generically mocked (Agent 5/6, absent a real
            # ANTHROPIC_API_KEY).
            form = self._read_form_body()
            result = submit_freeform(form.get("from", ""), form.get("subject", ""), form.get("body", ""))
            if result["status"] == "pending_gate2":
                RESOLVED.pop(result["submission_id"], None)
                PENDING[result["submission_id"]] = {
                    "project": result["project"], "trace": result["trace"], "scenario_key": None,
                }
                self._redirect(f"/dashboard/visualizer_{result['visualizer_id']}.html")
            else:
                self._redirect(f"/dashboard/visualizer_{result['result_id']}.html")
            return

        if parsed.path.startswith("/gate2/"):
            # Called via fetch() from the small decision iframe embedded in the right panel
            # (dashboard/render_gate2.py), not a normal form navigation — so this returns JSON
            # ({"redirect": ...}) instead of an HTTP redirect. The right panel's JS is what sends
            # the middle panel's flow graph on to that URL; this iframe itself never navigates.
            rest = parsed.path[len("/gate2/"):]
            if "/" not in rest:
                self._send_json({"error": "bad request"}, 400)
                return
            submission_id, decision = rest.split("/", 1)
            if decision not in ("accept", "reject", "hold"):
                self._send_json({"error": "decision must be accept, reject, or hold"}, 400)
                return
            if decision == "hold":
                # Not a real decision — the project is already sitting at status='analysis' in the
                # DB (run_intake_to_gate2 committed it there before Gate 2 ever opened), which is
                # the exact same condition the batch queue (§5.3) already queries for. Popping
                # PENDING is all that's needed at the data level: the in-memory trace shortcut goes
                # away, and the next time a PMO looks at this project it'll be through
                # /queue/review/, which reconstructs Agent 5/6's findings from audit_log the same
                # way a queued case 8/9/10 would. Deliberately NOT added to RESOLVED — holding isn't
                # a final decision.
                #
                # gate2_queue.html itself is a rendered snapshot, though, not a live query — every
                # other queue-mutating route (§5.3) re-renders it before redirecting there, and Hold
                # is no different, or the held project silently wouldn't show up until something
                # else happened to trigger a re-render.
                PENDING.pop(submission_id, None)
                render_gate2_queue()
                self._send_json({"redirect": "/dashboard/gate2_queue.html"})
                return
            if submission_id in RESOLVED:
                # Already decided (refresh, double-click, the iframe re-firing) — hand back the
                # same result instead of a confusing "not found".
                self._send_json({"redirect": f"/dashboard/visualizer_{RESOLVED[submission_id]}.html"})
                return
            pending = PENDING.pop(submission_id, None)
            if not pending:
                self._send_json({"error": "No pending Gate 2 decision found for that submission "
                                  "(the server may have restarted since this case was run)."}, 404)
                return
            form = self._read_form_body()
            result = resume_scenario(
                pending["project"], pending["trace"], decision,
                scenario_key=pending["scenario_key"],
                override_reason=form.get("reason"), pmo_comment=form.get("pmo_comment", ""),
                gate2_batch_id=pending.get("gate2_batch_id"), exception_reason=pending.get("exception_reason"),
            )
            RESOLVED[submission_id] = result["result_id"]
            self._send_json({"redirect": f"/dashboard/visualizer_{result['result_id']}.html"})
            return

        if parsed.path.startswith("/change/"):
            # Demo trigger for §7.2's Agents 11/12 — a normal form POST (target="middle-frame",
            # same pattern as /run/<key>), not a fetch(), since this isn't squeezed into a corner
            # panel the way Gate 2's decision UI is — a redirect is exactly right here.
            rest = parsed.path[len("/change/"):]
            if "/" not in rest:
                self._send_html("<h3>Bad request</h3>", 400)
                return
            project_ref, kind = rest.split("/", 1)
            if kind not in CHANGE_DEMO_PAYLOADS:
                self._send_html(f"<h3>Unknown change kind '{html.escape(kind)}'</h3>", 404)
                return
            result = submit_project_update(urllib.parse.unquote(project_ref), kind)
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/' target='_top'>Back</a></p>", 404)
                return
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/batch/"):
            # §5.3 demo trigger for cases 8/9/10 — normal form POST + redirect, same as /change/ and
            # /complete/. Fast-track results (case 9) need PENDING population exactly like /run/, so
            # the existing /gate2/ accept|reject route resolves them unchanged.
            case_key = parsed.path[len("/batch/"):]
            result = run_batch_case(case_key)
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/' target='_top'>Back</a></p>", 404)
                return
            if result.get("queued") is False:
                RESOLVED.pop(result["submission_id"], None)
                PENDING[result["submission_id"]] = {
                    "project": result["project"], "trace": result["trace"], "scenario_key": None,
                    "exception_reason": result.get("exception_reason"),
                }
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/queue/review/"):
            submission_id = urllib.parse.unquote(parsed.path[len("/queue/review/"):])
            result = review_queued_project(submission_id)
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/dashboard/gate2_queue.html' target='_top'>Back to queue</a></p>", 400)
                return
            RESOLVED.pop(submission_id, None)
            PENDING[submission_id] = {
                "project": result["project"], "trace": result["trace"], "scenario_key": None,
                "gate2_batch_id": result.get("gate2_batch_id"), "exception_reason": result.get("exception_reason"),
            }
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/queue/override/"):
            submission_id = urllib.parse.unquote(parsed.path[len("/queue/override/"):])
            form = self._read_form_body()
            result = override_queued_project(submission_id, form.get("reason", ""))
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/dashboard/gate2_queue.html' target='_top'>Back to queue</a></p>", 400)
                return
            RESOLVED.pop(submission_id, None)
            PENDING[submission_id] = {
                "project": result["project"], "trace": result["trace"], "scenario_key": None,
                "gate2_batch_id": result.get("gate2_batch_id"), "exception_reason": result.get("exception_reason"),
            }
            self._redirect(result["redirect"])
            return

        if parsed.path == "/queue/open-batch":
            result = open_batch()
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/queue/close-batch/"):
            batch_id_str = parsed.path[len("/queue/close-batch/"):]
            try:
                batch_id = int(batch_id_str)
            except ValueError:
                self._send_html("<h3>Bad request</h3>", 400)
                return
            result = close_batch(batch_id)
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/complete/"):
            # Demo trigger for §7.2.3's Agent 13 — normal form POST + redirect, same as /change/.
            project_ref = urllib.parse.unquote(parsed.path[len("/complete/"):])
            if not project_ref:
                self._send_html("<h3>Bad request</h3>", 400)
                return
            result = complete_project(project_ref)
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/' target='_top'>Back</a></p>", 404)
                return
            self._redirect(result["redirect"])
            return

        if parsed.path.startswith("/gate3/"):
            # Same JSON-not-redirect contract as /gate2/ — the Gate 3 page (dashboard/render_gate3.py)
            # submits via fetch() and self-navigates on success, so this stays consistent even though
            # Gate 3 fills the whole middle panel and doesn't strictly need the fetch() trick Gate 2
            # needed to avoid navigating the wrong iframe.
            rest = parsed.path[len("/gate3/"):]
            if "/" not in rest:
                self._send_json({"error": "bad request"}, 400)
                return
            change_request_id, decision = rest.split("/", 1)
            if decision not in ("accept", "reject"):
                self._send_json({"error": "decision must be accept or reject"}, 400)
                return
            try:
                change_request_id = int(change_request_id)
            except ValueError:
                self._send_json({"error": "bad change_request_id"}, 400)
                return
            form = self._read_form_body()
            result = resolve_gate3_decision(change_request_id, decision, pmo_comment=form.get("pmo_comment", ""))
            if "error" in result:
                self._send_json(result, 404)
                return
            self._send_json({"redirect": result["redirect"]})
            return

        self._send_html("<h3>Not found</h3>", 404)

def main():
    # So the toolbar's "Gate 2 Queue" link (and the queue's own PMO-facing entry point, per the
    # user's ask to "access directly into the list of projects pending approval") never 404s on a
    # fresh server start just because no batch case has been run yet — an empty queue is a real,
    # renderable state, not an error.
    render_gate2_queue()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Composer running at http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
