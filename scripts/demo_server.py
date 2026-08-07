"""
In-browser demo composer (§0's simulated-intake decision, §12.1 entry point) — a local-only web
server (stdlib only, no new dependencies).

Layout (§14 restructure — the old topline dashboard, portfolio activity feed, and stakeholder
Comment & Concern panel are gone; this is what replaced them):
  - Top:    a full-width notifications strip, PLUS the Gate 2 decision UI when one is needed.
            Notifications are not a static list — the visualizer posts a message the instant each
            notification's triggering step completes during replay, so a card appears here in sync
            with the graph, not before or after. When a run reaches Manual Gate 2, the decision form
            (Accept/Reject/Hold) opens here too, ABOVE the feed — never in the middle panel — so a
            PMO can make the call without losing sight of the flow graph they were just watching.
  - Left:   the 7 named scenarios as predrafted "submission emails" (data/trial-projects.json's
            scenario_index, §12), each with a "Run this case" button — plus the two compose boxes,
            then an "active projects" panel (dashboard/render_active_projects.py's
            render_active_fragment(), §14 follow-up) showing every accepted/in_progress project's
            live risk/schedule/resource/CAPEX status — the confirmation view for "did my project
            update actually apply," which had no replacement after the topline dashboard was
            removed — and finally the Periodic Gate 2 Review queue (§5.3) embedded directly
            (dashboard/render_gate2_queue.py's render_queue_fragment()), listing every project
            sitting at status='analysis' right now, including this week's 5-project batch (§14).
            This is the one real entry point for "review a queued project and Accept/Reject/Hold
            it" — the old topline dashboard used to embed the same fragment; it now lives here
            instead.
  - Middle: an iframe showing whatever's happening — Gate 2 review if a PMO decision is needed, or
            the live execution visualizer once it's resolved. No default page (nothing to jump to
            now that the dashboard/activity feed are gone) — it starts blank until a case runs.
Both remaining panels are drag-resizable (grab the thin divider between them) — widths persist in
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
import sys, os, re, html, json, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from demo_engine import (
    run_scenario_to_gate2, resume_scenario, SCENARIO_ORDER, SCENARIO_META, SCENARIO_EMAILS,
    submit_project_update, resolve_gate3_decision, CHANGE_DEMO_PAYLOADS, CHANGE_CASE_EMAILS,
    complete_project, run_batch_case, review_queued_project, override_queued_project, open_batch,
    close_batch, render_gate2_queue, submit_freeform, FREEFORM_BODY_PLACEHOLDER,
    submit_project_update_freeform, reset_demo, get_updatable_projects, UPDATE_BODY_PLACEHOLDER,
    CASE10_EMAIL,
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from dashboard.render_gate2_queue import render_queue_fragment
from dashboard.render_active_projects import render_active_fragment
from src.orchestration.pipeline import Gate2OverrideRequiredError
# Note: run_batch_case/review_queued_project/override_queued_project/open_batch/close_batch and
# their /batch/, /queue/* HTTP routes below are kept fully wired even though the "Periodic Gate 2
# Review" left-panel dropdown entry that used to trigger cases 8a/8b/9/10 by button is gone (per an
# explicit ask to move to "the real queue view" instead of demo-seed buttons) — the embedded queue
# now in the composer's left panel (dashboard/render_gate2_queue.py, §14) POSTs to these exact same
# routes for its own Open batch / Close batch / Review & decide / Pull from queue controls, so none
# of this backend logic became dead code, only its old one-click seed buttons did.

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD_DIR = os.path.join(REPO_ROOT, "dashboard")
PORT = 8765

# ── Persistent PENDING / RESOLVED ────────────────────────────────────────────
# Persisted to a JSON file so a server restart doesn't wipe Gate 2 state that
# was set up in a prior run — the PMO can restart the server and still Accept /
# Reject / Hold without having to re-run the case from scratch.
_STATE_FILE = os.path.join(REPO_ROOT, ".pending_state.json")

def _load_state():
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                d = json.load(f)
            return d.get("pending", {}), d.get("resolved", {})
        except Exception:
            pass
    return {}, {}

def _save_state():
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({"pending": PENDING, "resolved": RESOLVED}, f)
    except Exception:
        pass

PENDING, RESOLVED = _load_state()

PAGE_CSS = """
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#1a1a1a;display:flex;flex-direction:column;height:100vh}
#topbar{flex-shrink:0;background:#fafaf8;display:flex;flex-direction:column;max-height:50vh}
#topbar h3{font-size:13px;margin:0;padding:12px 14px;border-bottom:1px solid #e5e3dc;background:#fff;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
#revert-btn{background:#f1efe8;color:#5f5e5a;border:1px solid #ddd;border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer}
#revert-btn:hover{background:#e5e3dc;color:#1a1a1a}
#app{flex:1;display:flex;min-height:0}
#left{width:360px;flex-shrink:0;overflow-y:auto;padding:1.25rem;background:#fafaf8}
#left h2{font-size:16px;margin:0 0 4px}
#left .sub{color:#5f5e5a;font-size:12px;margin-bottom:18px;line-height:1.5}
#middle{flex:1;display:flex;flex-direction:column;min-width:0}
#middle iframe{flex:1;border:none;width:100%}
.resizer{width:6px;flex-shrink:0;cursor:col-resize;background:#e5e3dc;position:relative;transition:background .15s}
.resizer:hover,.resizer.active{background:#378ADD}
.resizer::after{content:'';position:absolute;top:0;bottom:0;left:-3px;right:-3px}
#decision-area:empty{display:none}
#decision-area{flex-shrink:0;max-height:40vh;overflow-y:auto;border-bottom:3px solid #378ADD;background:#fff}
#decision-area iframe{width:100%;height:400px;border:none;display:block}
#notif-feed{display:flex;gap:10px;overflow-x:auto;padding:12px;flex-shrink:0}
#notif-feed .empty{color:#999;font-size:12px;padding:8px 4px}
.notifcard{border:1px solid #e5e3dc;border-radius:8px;overflow:hidden;background:#fff;animation:pop .25s ease-out;flex:0 0 280px;max-height:160px;display:flex;flex-direction:column}
@keyframes pop {{ from {{ opacity:0; transform:translateY(-4px); }} to {{ opacity:1; transform:translateY(0); }} }}
.notifcard .nhead{font-size:10px;color:#378ADD;font-weight:600;background:#e6f1fb;padding:5px 10px}
.notifcard .nsubject{font-size:12px;font-weight:600;padding:8px 10px 0}
.notifcard .nbody{font-size:11px;color:#444;padding:4px 10px 10px;white-space:pre-wrap;line-height:1.5;flex:1;overflow-y:auto}
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
#compose,#update-compose{border:1px solid #e5e3dc;border-radius:10px;padding:10px 12px;background:#fff}
#compose label,#update-compose label{font-size:11px;color:#5f5e5a;display:block;margin-bottom:3px}
#compose input,#compose textarea,#compose select,#update-compose input,#update-compose textarea,#update-compose select{width:100%;font-size:12px;font-family:inherit;padding:6px 8px;border:1px solid #e5e3dc;border-radius:6px;margin-bottom:10px;box-sizing:border-box}
#compose textarea{height:120px;resize:vertical}
#update-compose .empty{color:#888;font-size:12px;padding:6px 2px}
/* Ghost-text body editor (shared by both compose boxes): the label before each colon is real, fixed
   text (contenteditable="false") — always there, can't be typed over or deleted — while the hint
   after it is greyed-out ghost text that clears the instant you click into the row, so you can type
   the value straight in without re-typing or remembering the field name. */
.body-editable{width:100%;font-size:12px;font-family:inherit;padding:8px;border:1px solid #e5e3dc;border-radius:6px;box-sizing:border-box;min-height:110px;line-height:1.8;cursor:text;margin-bottom:10px}
.body-editable:focus{outline:2px solid #d8d4c8;outline-offset:1px}
.uline{white-space:pre-wrap}
.uline.note-row,.uline.spaced{margin-top:10px}
.uline .lbl{color:#2a2a28}
.uline .ghost{color:#a8a49a}
.uline .filled{color:#2a2a28}
/* Periodic Gate 2 Review queue (dashboard/render_gate2_queue.py's render_queue_fragment()),
   embedded directly here instead of on the now-removed topline dashboard (§14). Scoped under
   #queue-embed since the fragment's own class names (table/th/td/.badge/.empty/button) would
   otherwise clash with — or get overridden by — this page's existing generic rules. */
#queue-embed{margin-top:8px}
#queue-embed table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:4px}
#queue-embed th{text-align:left;color:#5f5e5a;font-weight:400;font-size:11px;padding:6px 4px;border-bottom:1px solid #ddd}
#queue-embed td{padding:6px 4px;border-bottom:1px solid #eee;vertical-align:top}
#queue-embed .badge{font-size:11px;padding:2px 8px;border-radius:6px}
#queue-embed .green{background:#eaf3de;color:#3b6d11}
#queue-embed .yellow{background:#faeeda;color:#854f0b}
#queue-embed .red{background:#fcebeb;color:#a32d2d}
#queue-embed .gray{background:#f1efe8;color:#5f5e5a}
#queue-embed .banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px}
#queue-embed .banner b{color:#1a5a92}
#queue-embed .batch-status{display:flex;justify-content:space-between;align-items:center;background:#f5f4f0;border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:12px;flex-wrap:wrap;gap:8px}
#queue-embed .batch-status form{margin:0}
#queue-embed .rollups{display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:16px}
#queue-embed .rollup{border-radius:8px;padding:10px 12px;font-size:11px;line-height:1.5}
#queue-embed .rollup.ok{background:#eaf3de;border:1px solid #a8d18d}
#queue-embed .rollup.over{background:#fdf2f2;border:1px solid #f0c9c9}
#queue-embed .rollup .region{font-weight:600;font-size:12px;margin-bottom:4px}
#queue-embed .rollup.ok .region{color:#3b6d11}
#queue-embed .rollup.over .region{color:#a32d2d}
#queue-embed .override-form{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
#queue-embed .override-form input{font-size:11px;border:1px solid #ddd;border-radius:4px;padding:3px 6px;width:100px}
#queue-embed .override-form button{padding:3px 8px;font-size:11px;background:#ef9f27}
#queue-embed .override-form button:hover{background:#d98a1a}
#queue-embed .empty{color:#888;font-size:12px;padding:14px;text-align:center}
#queue-embed h3{font-size:12px;margin:10px 0 6px}
/* Queued-projects table collapses behind a native <details> (dashboard/render_gate2_queue.py) —
   one row per queued project is the tallest, most repetitive part of this narrow left-panel embed,
   so it starts closed rather than always pushing everything below it down the page. */
#queue-embed .queue-details summary{font-size:12px;font-weight:600;margin:10px 0 6px;cursor:pointer;color:#1a1a1a;list-style-position:outside}
#queue-embed .queue-details summary:hover{color:#378ADD}
#queue-embed .queue-details table{margin-top:8px}
/* Active projects — live risk/schedule/resource view (dashboard/render_active_projects.py's
   render_active_fragment()), §14 follow-up. Same scoping approach and visual language as
   #queue-embed above, under its own #active-embed prefix so neither fragment's badge/table/details
   rules bleed into the other. This is the confirmation view for "did my update actually apply" —
   the topline dashboard used to be the only place that showed live risk/schedule/resource state;
   nothing replaced it when that dashboard was removed until now. */
#active-embed{margin-top:8px}
#active-embed table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:4px}
#active-embed th{text-align:left;color:#5f5e5a;font-weight:400;font-size:11px;padding:6px 4px;border-bottom:1px solid #ddd}
#active-embed td{padding:6px 4px;border-bottom:1px solid #eee;vertical-align:top}
#active-embed .badge{font-size:11px;padding:2px 8px;border-radius:6px}
#active-embed .green{background:#eaf3de;color:#3b6d11}
#active-embed .yellow{background:#faeeda;color:#854f0b}
#active-embed .red{background:#fcebeb;color:#a32d2d}
#active-embed .gray{background:#f1efe8;color:#5f5e5a}
#active-embed .banner{background:#e6f1fb;border:1px solid #378ADD;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px}
#active-embed .banner b{color:#1a5a92}
#active-embed .empty{color:#888;font-size:12px;padding:14px;text-align:center}
#active-embed h3{font-size:12px;margin:10px 0 6px}
#active-embed .active-details summary{font-size:12px;font-weight:600;margin:10px 0 6px;cursor:pointer;color:#1a1a1a;list-style-position:outside}
#active-embed .active-details summary:hover{color:#378ADD}
#active-embed .active-details table{margin-top:8px}
"""

# Ghost-text body editor (shared by "or submit your own" and "or send a project update"): parses a
# placeholder string's "Label: <hint>" lines into (real fixed label, greyed-out hint) row HTML. Built
# from FREEFORM_BODY_PLACEHOLDER / UPDATE_BODY_PLACEHOLDER themselves (both from demo_engine.py,
# ultimately from src/agents/agent1_intake_parser.py and agent11_update_logger.py) rather than
# hand-duplicated label text, so the on-screen hint and the parser it documents can never drift
# apart. Blank lines in the placeholder become spacing between rows (a "spaced" class), not literal
# blank rows — this renders as a block-level DIV layout, not a raw textarea character stream.
_GHOST_LINE_RE = re.compile(r"^(?P<label>.+?:\s*\$?)<(?P<hint>.+)>$")


def _ghost_editor_rows(placeholder_text):
    rows_html = []
    first_in_group = True
    for raw_line in placeholder_text.splitlines():
        if not raw_line.strip():
            first_in_group = True
            continue
        m = _GHOST_LINE_RE.match(raw_line)
        if not m:
            continue
        label, hint = m.group("label"), m.group("hint")
        cls = " spaced" if (rows_html and first_in_group) else ""
        rows_html.append(
            f'<div class="uline{cls}">'
            f'<span class="lbl" contenteditable="false">{html.escape(label)}</span>'
            f'<span class="ghost" data-hint="{html.escape(hint)}">{html.escape(hint)}</span>'
            f'</div>'
        )
        first_in_group = False
    return "".join(rows_html)


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

    # Cases 8/9/10 — post-acceptance change management (Agents 11/12) and completion (Agent 13),
    # each narrowed to a single action per dropdown entry so they match cases 1-7's one-case,
    # one-outcome pattern instead of a single card with three competing buttons. All three still run
    # against Case 1's already-accepted project (PRJ-2026-0791) — nothing about the underlying
    # actions changed, only how they're exposed in the left panel.
    options.append('<option value="case8">Case 8 — Project update to increase launch date</option>')
    fav_email = CHANGE_CASE_EMAILS["favorable"]
    panels.append(f"""
<div class="action-panel" id="panel-case8">
<div class="case" style="border-color:#dceafa">
  <div class="head" style="background:#e6f1fb"><span class="title">Case 8 — Project update to increase launch date</span>
  <span class="outcome">Expected: Agent 12 applies it immediately, no PMO gate</span></div>
  <div class="mail">
    <div class="line"><b>From:</b> {html.escape(fav_email['from'])}</div>
    <div class="line"><b>Subject:</b> {html.escape(fav_email['subject'])}</div>
    <div class="body">{html.escape(fav_email['body'])}</div>
  </div>
  <form class="runbar" method="POST" action="/change/PRJ-2026-0791/favorable" target="middle-frame">
    <button type="submit">▶ Run this case</button>
  </form>
</div>
</div>""")

    options.append('<option value="case9">Case 9 — Project update needing PMO authorization</option>')
    unfav_email = CHANGE_CASE_EMAILS["unfavorable"]
    panels.append(f"""
<div class="action-panel" id="panel-case9">
<div class="case" style="border-color:#dceafa">
  <div class="head" style="background:#e6f1fb"><span class="title">Case 9 — Project update needing PMO authorization</span>
  <span class="outcome">Expected: Agent 12 escalates to Manual Gate 3</span></div>
  <div class="mail">
    <div class="line"><b>From:</b> {html.escape(unfav_email['from'])}</div>
    <div class="line"><b>Subject:</b> {html.escape(unfav_email['subject'])}</div>
    <div class="body">{html.escape(unfav_email['body'])}</div>
  </div>
  <form class="runbar" method="POST" action="/change/PRJ-2026-0791/unfavorable" target="middle-frame">
    <button type="submit">▶ Run this case</button>
  </form>
</div>
</div>""")

    options.append('<option value="case10">Case 10 — Project update: complete, generate OPL (Agent 13)</option>')
    panels.append(f"""
<div class="action-panel" id="panel-case10">
<div class="case" style="border-color:#dceafa">
  <div class="head" style="background:#e6f1fb"><span class="title">Case 10 — Project update: complete, generate OPL (Agent 13)</span>
  <span class="outcome">Expected: Project marked completed, OPL composed and published, originator notified with the link</span></div>
  <div class="mail">
    <div class="line"><b>From:</b> {html.escape(CASE10_EMAIL['from'])}</div>
    <div class="line"><b>Subject:</b> {html.escape(CASE10_EMAIL['subject'])}</div>
    <div class="body">{html.escape(CASE10_EMAIL['body'])}</div>
  </div>
  <form class="runbar" method="POST" action="/complete/PRJ-2026-0791" target="middle-frame">
    <button type="submit">▶ Run this case</button>
  </form>
</div>
</div>""")

    compose_section = f"""
<div class="divider"><div class="line"></div><span>or submit your own</span><div class="line"></div></div>
<div id="compose">
  <form method="POST" action="/submit" target="middle-frame" id="c-form">
    <label for="c-from">From</label>
    <input id="c-from" name="from" type="text" placeholder="name@company.com" />
    <label for="c-subject">Subject</label>
    <input id="c-subject" name="subject" type="text" placeholder="Proposal — project name" />
    <label for="c-body">Body</label>
    <div id="c-body-editable" class="body-editable" contenteditable="true" spellcheck="false">{_ghost_editor_rows(FREEFORM_BODY_PLACEHOLDER)}</div>
    <textarea id="c-body" name="body" style="display:none"></textarea>
    <div class="runbar" style="padding:0;border-top:none">
      <button type="submit">✉ Submit for review</button>
    </div>
  </form>
</div>
<div class="sub" style="margin-top:8px">Click any greyed-out hint to fill it in — the label stays
put, only the hint clears. Runs through the real pipeline — Agent 1 parses whatever's typed
(deterministic fallback in demo mode, so it works best matching the placeholder's shape), Agent 2
checks it against the real seeded trial projects for duplicates. Agent 5/6 use one generic mock
response in demo mode (no ANTHROPIC_API_KEY); set that env var and they judge it for real too.</div>"""

    # "The list is an interactive database" — pick any accepted/in_progress project (real, live DB
    # state via get_updatable_projects(), not the trial-data snapshot) and send it a real update
    # email, parsed by Agent 11's own deterministic parser (src/agents/agent11_update_logger.py's
    # parse_update_email()). Moved here from the (now-removed) topline dashboard's middle-panel
    # widget — this is the left panel's other real entry point now, right below "or submit your own".
    # target="middle-frame" so the result (auto-applied, or escalated to a real Manual Gate 3) shows
    # in the middle panel exactly like every other left-panel action, and notifications still surface
    # in the top notifications strip via the same _redirect_with_notification() relay Case 8/9 use
    # (see dashboard/render_gate2_queue.py's own copy of that relay script).
    updatable_rows = get_updatable_projects()
    update_options = "".join(
        f'<option value="{html.escape(r["project_id"] or r["submission_id"])}" '
        f'data-name="{html.escape(r["project_name"] or "")}" '
        f'data-submitter="{html.escape(r["submitter_name"] or "")}">'
        f'{html.escape(r["project_name"] or "")} ({html.escape(r["project_id"] or r["submission_id"])})</option>'
        for r in updatable_rows
    )
    update_section = f"""
<div class="divider"><div class="line"></div><span>or send a project update</span><div class="line"></div></div>
<div id="update-compose">
{'<div class="empty">No accepted or in-progress projects to update right now.</div>' if not updatable_rows else f'''
<form method="POST" action="/project-update/submit" target="middle-frame" id="u-form">
  <label for="u-project">Project</label>
  <select id="u-project" name="project_ref" required>{update_options}</select>
  <label for="u-from">From</label>
  <input id="u-from" name="from" type="text" required>
  <label for="u-subject">Subject</label>
  <input id="u-subject" name="subject" type="text" required>
  <label for="u-body">Body</label>
  <div id="u-body-editable" class="body-editable" contenteditable="true" spellcheck="false">{_ghost_editor_rows(UPDATE_BODY_PLACEHOLDER)}</div>
  <textarea id="u-body" name="body" style="display:none"></textarea>
  <div class="runbar" style="padding:0;border-top:none">
    <button type="submit">✉ Submit update</button>
  </div>
</form>
<div class="sub" style="margin-top:8px">Click any greyed-out hint to fill it in — the label stays
put, only the hint clears. Leave a hint untouched to skip that field. Runs through the real pipeline
— Agent 11 captures whatever's typed, Agent 12 evaluates it and either applies it directly or opens a
real Manual Gate 3 for PMO to accept, decline, or cancel the project.</div>
'''}
</div>"""

    # Active projects — live risk/schedule/resource view (§14 follow-up). Sits right below "send a
    # project update" so the natural flow is: submit an update above, then check here that it
    # actually took effect — a schedule-only change auto-applies immediately with no notification
    # and no Gate 3 (Agent 12 doesn't treat schedule_status alone as governance-relevant), so this
    # is the only place that confirms it. Same render_active_fragment() computation the standalone
    # active_projects.html page uses.
    active_fragment, active_len = render_active_fragment(get_connection())
    active_section = f"""
<div class="divider"><div class="line"></div><span>active projects{f' ({active_len})' if active_len else ''}</span><div class="line"></div></div>
<div id="active-embed">{active_fragment}</div>"""

    # Periodic Gate 2 Review queue (§5.3, §14) — embedded directly in the left panel now that the
    # topline dashboard that used to hold it is gone. Same render_queue_fragment() computation the
    # standalone gate2_queue.html page uses (see that module's docstring) — never two copies of this
    # logic that could drift apart.
    queue_fragment, queue_len = render_queue_fragment(get_connection())
    queue_section = f"""
<div class="divider"><div class="line"></div><span>this week's Gate 2 batch{f' ({queue_len} pending)' if queue_len else ''}</span><div class="line"></div></div>
<div id="queue-embed">{queue_fragment}</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PMO Intake — Composer</title>
<style>{PAGE_CSS}</style></head><body>
<div id="topbar">
  <h3>📧 Notifications
    <form method="POST" action="/reset" target="_top" style="margin:0" onsubmit="return confirm('Revert the demo? This wipes and reseeds the database and clears everything run so far.');">
      <button type="submit" id="revert-btn">↺ Revert back</button>
    </form>
  </h3>
  <div id="decision-area"></div>
  <div id="notif-feed"><div class="empty">Nothing sent yet — run a case and this fills in as the flow reaches each notification step.</div></div>
</div>
<div id="app">
  <div id="left">
    <h2>PMO Project Intake — composer</h2>
    <div class="sub">Choose a case, or compose your own below, then run it through the real agent
    pipeline. Middle panel shows the flow — Gate 2 review if a PMO decision is needed, then the live
    execution graph. The notifications strip above fills in with each notification the instant its
    step fires during replay.</div>
    <select id="action-select">{"".join(options)}</select>
    {"".join(panels)}
    {compose_section}
    {update_section}
    {active_section}
    {queue_section}
  </div>
  <div class="resizer" id="resize-left" title="Drag to resize"></div>
  <div id="middle">
    <iframe name="middle-frame" id="middle-frame"></iframe>
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

// Ghost-text body editor (shared by both compose boxes below the case dropdown): each row's label
// span is contenteditable="false" (real, fixed text, can't be typed over or deleted) and its value
// span starts as grey "ghost" hint text. Clicking anywhere on the row clears the hint and lets you
// type the real value; leaving it empty restores the hint. Right before submit, only rows actually
// filled in get assembled into the hidden textarea, one "Label: value" per line, in document order —
// untouched hints are correctly treated as "not stated", never submitted as literal placeholder text.
function initGhostEditor(editorId, hiddenId, formId) {{
  var editable = document.getElementById(editorId);
  if (!editable) return;
  var hidden = document.getElementById(hiddenId);
  var form = document.getElementById(formId);
  var lastActive = null;

  function placeCaretInside(span) {{
    var range = document.createRange();
    range.selectNodeContents(span);
    range.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }}
  function restoreIfEmpty(span) {{
    if (span && span.classList.contains('filled') && span.textContent.trim() === '') {{
      span.classList.remove('filled');
      span.classList.add('ghost');
      span.textContent = span.dataset.hint;
    }}
  }}
  function activate(span) {{
    if (lastActive && lastActive !== span) restoreIfEmpty(lastActive);
    if (span.classList.contains('ghost')) {{
      span.classList.remove('ghost');
      span.classList.add('filled');
      span.textContent = '';
    }}
    placeCaretInside(span);
    lastActive = span;
  }}
  Array.prototype.forEach.call(editable.querySelectorAll('.uline'), function(row) {{
    row.addEventListener('mousedown', function(e) {{
      e.preventDefault();
      editable.focus();
      activate(row.querySelector('.ghost, .filled'));
    }});
  }});
  editable.addEventListener('blur', function() {{ restoreIfEmpty(lastActive); }});

  if (form) {{
    form.addEventListener('submit', function(e) {{
      restoreIfEmpty(lastActive);
      var lines = [];
      Array.prototype.forEach.call(editable.querySelectorAll('.uline'), function(row) {{
        var val = row.querySelector('.filled');
        if (val) lines.push(row.querySelector('.lbl').textContent + val.textContent.trim());
      }});
      hidden.value = lines.join('\\n');
      if (!hidden.value.trim()) {{
        e.preventDefault();
        alert('Click a hint and fill in at least one field before submitting.');
      }}
    }});
  }}
}}
initGhostEditor('c-body-editable', 'c-body', 'c-form');
initGhostEditor('u-body-editable', 'u-body', 'u-form');

// Prefill From/Subject on the update box from the picked project's real data (submitter_name,
// project_name) — never fabricated, just what's already on the row — and re-fill on selection change.
(function() {{
  var select = document.getElementById('u-project');
  if (!select) return;
  function fillFromSelection() {{
    var opt = select.options[select.selectedIndex];
    if (!opt) return;
    var name = opt.dataset.submitter || 'Project team';
    document.getElementById('u-from').value = name + ' <' + name.toLowerCase().replace(/[^a-z]+/g, '.') + '@company.com>';
    document.getElementById('u-subject').value = 'Update: ' + (opt.dataset.name || '');
  }}
  select.addEventListener('change', fillFromSelection);
  fillFromSelection();
}})();

// Draggable panel resizing — the left panel remembers its width in localStorage (this is a real
// local page in a real browser, not a sandboxed artifact preview, so persisting the layout across
// reloads is safe and just a convenience). Middle panel always fills whatever's left via flex:1, so
// only left needs an explicit width. (The right panel this used to also resize is gone — §14 moved
// its contents to the top notifications strip, which spans the full width and isn't resized.)
(function() {{
  const leftPanel = document.getElementById('left');
  const savedLeft = localStorage.getItem('pmo_composer_left_width');
  if (savedLeft) leftPanel.style.width = savedLeft + 'px';

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
                _save_state()
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
                _save_state()
                self._redirect(f"/dashboard/visualizer_{result['visualizer_id']}.html")
            else:
                self._redirect(f"/dashboard/visualizer_{result['result_id']}.html")
            return

        if parsed.path == "/project-update/submit":
            # "The list is an interactive database" — the left panel's "or send a project update" box
            # (render_landing()'s update_section, moved here from dashboard/render_topline.py's
            # middle-panel dashboard), a real update against whichever accepted/in_progress project
            # was picked. Normal form POST + redirect, same as /change/ — target="middle-frame" so the
            # result lands in the middle panel's iframe exactly like every other left-panel action.
            form = self._read_form_body()
            result = submit_project_update_freeform(
                form.get("project_ref", ""), form.get("from", ""), form.get("subject", ""), form.get("body", ""),
            )
            if "error" in result:
                self._send_html(f"<h3>{html.escape(result['error'])}</h3><p><a href='/' target='_top'>Back to composer</a></p>", 400)
                return
            self._redirect(result["redirect"])
            return

        if parsed.path == "/reset":
            # "Revert back" (top-right of the right panel) — wipes and reseeds the DB, clears this
            # server's in-memory PENDING/RESOLVED decision state, and regenerates every dashboard
            # page back to its pristine post-seed state, so a demo can restart clean without
            # restarting the actual server process.
            reset_demo()
            PENDING.clear()
            RESOLVED.clear()
            self._redirect("/")
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
                _save_state()
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
            # For a PMO override-accept (Agent 6 verdict was misaligned/inconclusive),
            # the Gate 2 form sends pmo_override_reason as a required field; merge it into
            # pmo_comment so it's visible in the acceptance notification, prefixed clearly. Also
            # passed through as its own kwarg below — resume_after_gate2() checks it for real
            # (Gate2OverrideRequiredError, not just this form's own JS validation), since a client
            # requirement alone is bypassable by anyone who POSTs here directly.
            pmo_override = form.get("pmo_override_reason", "").strip()
            pmo_comment = form.get("pmo_comment", "").strip()
            if pmo_override:
                pmo_comment = f"[PMO override: {pmo_override}]" + (f" — {pmo_comment}" if pmo_comment else "")
            try:
                result = resume_scenario(
                    pending["project"], pending["trace"], decision,
                    scenario_key=pending["scenario_key"],
                    override_reason=form.get("reason"), pmo_comment=pmo_comment,
                    gate2_batch_id=pending.get("gate2_batch_id"), exception_reason=pending.get("exception_reason"),
                    pmo_override_reason=pmo_override,
                )
            except Gate2OverrideRequiredError as e:
                # Validation failed — put the pending decision back exactly as it was (this session's
                # PENDING already popped it above) so the PMO can retry with a real reason instead of
                # the case silently disappearing from the queue.
                PENDING[submission_id] = pending
                self._send_json({"error": str(e)}, 400)
                return
            RESOLVED[submission_id] = result["result_id"]
            _save_state()
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
                _save_state()
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
            _save_state()
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
            if decision not in ("accept", "reject", "cancel"):
                self._send_json({"error": "decision must be accept, reject, or cancel"}, 400)
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
