"""
Live Execution Visualizer, replay mode (§9.1, Phase 4.2 — replay only, live polling deferred per
BUILD-TASKS.md). Reads real audit_log rows for one project and replays them client-side at a fixed
pace via JS — a directed graph of the actual 1-10 pipeline (§2), with the real path this submission
took lighting up node-by-node and edge-by-edge, CrewAI-flow style, plus a scrolling execution log.
Only the nodes/edges this specific run actually touched light up; the rest of the graph stays
dimmed to show the paths that existed but weren't taken (duplicate-reject, misaligned-reject, etc).
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection

AGENT_LABELS = {
    "agent1_intake_parser": "Agent 1 · Intake parser",
    "agent2_duplicate_checker": "Agent 2 · Duplicate checker",
    "agent3_duplicate_rejection_notifier": "Agent 3 · Duplicate rejection notifier",
    "agent4_pmo_router": "Agent 4 · PMO router / acknowledgment",
    "agent5_business_impact": "Agent 5 · Business impact",
    "agent6_knowledge_crosscheck": "Agent 6 · Knowledge cross-check",
    "agent7_acceptance_handler": "Agent 7 · Acceptance handler",
    "agent8_rejection_feedback_composer": "Agent 8 · Rejection feedback",
    "agent9_dashboard_service": "Agent 9 · Dashboard publish",
    "agent10_success_predictor": "Agent 10 · Success predictor",
}

# Static architecture of the pipeline (§2/§8) — every node and edge that CAN exist, regardless of
# which path any one submission actually takes. (cx, cy, w, h, shape, two-line label)
#
# Two columns: LEFT is the main trunk (Agent 1 through Gate 2) continuing straight down into the
# accept path (Agent 7 -> 9 -> 10 -> Accepted) — the happy path stays one straight vertical line,
# no diagonal jump. RIGHT holds every alternate/exit branch off that trunk: incomplete-at-intake,
# duplicate, inconclusive-under-review, and Gate 2's reject path (Agent 8 -> Rejected). This keeps
# the whole graph visible in one screen's width instead of three columns sprawling sideways.
COL_MAIN = 230
COL_ALT = 510
NODE_POS = {
    "agent1_intake_parser":              (COL_MAIN,  35, 176, 52, "box",     "Agent 1\nIntake Parser"),
    "agent2_duplicate_checker":          (COL_MAIN, 130, 176, 52, "box",     "Agent 2\nDuplicate Checker"),
    "agent3_duplicate_rejection_notifier":(COL_ALT, 130, 176, 52, "box",    "Agent 3\nDuplicate Reject Notify"),
    "end_incomplete":                    (COL_ALT,  35, 176, 40, "chip",    "Rejected\nIncomplete info"),
    "gate1":                             (COL_MAIN, 220,  96, 84, "diamond", "Gate 1\nProceed"),
    "agent4_pmo_router":                 (COL_MAIN, 315, 176, 52, "box",     "Agent 4\nPMO Router / Ack"),
    "agent5_business_impact":            (COL_MAIN, 400, 176, 52, "box",     "Agent 5\nBusiness Impact"),
    "agent6_knowledge_crosscheck":       (COL_MAIN, 485, 176, 52, "box",     "Agent 6\nKnowledge Cross-Check"),
    "end_review":                        (COL_ALT, 485, 176, 40, "chip",    "Under Review\nInconclusive"),
    "gate2":                             (COL_MAIN, 580,  96, 84, "diamond", "Gate 2\nPMO Decision"),
    "agent7_acceptance_handler":         (COL_MAIN, 680, 176, 52, "box",     "Agent 7\nAcceptance Handler"),
    "agent9_dashboard_service":          (COL_MAIN, 765, 176, 52, "box",     "Agent 9\nDashboard Publish"),
    "agent10_success_predictor":         (COL_MAIN, 850, 176, 52, "box",     "Agent 10\nSuccess Predictor"),
    "end_accepted":                      (COL_MAIN, 925, 176, 40, "chip",    "Accepted"),
    "agent8_rejection_feedback_composer":(COL_ALT, 680, 176, 52, "box",     "Agent 8\nRejection Feedback"),
    "end_rejected":                      (COL_ALT, 765, 176, 40, "chip",    "Rejected"),
}

NODE_POS["end_dup"] = (COL_ALT, 220, 176, 40, "chip", "Rejected\nDuplicate")

EDGES = [
    ("agent1_intake_parser", "agent2_duplicate_checker"),
    ("agent1_intake_parser", "end_incomplete"),
    ("agent2_duplicate_checker", "gate1"),
    ("agent2_duplicate_checker", "agent3_duplicate_rejection_notifier"),
    ("agent3_duplicate_rejection_notifier", "end_dup"),
    ("gate1", "agent4_pmo_router"),
    ("agent4_pmo_router", "agent5_business_impact"),
    ("agent5_business_impact", "agent6_knowledge_crosscheck"),
    ("agent6_knowledge_crosscheck", "gate2"),
    ("agent6_knowledge_crosscheck", "end_review"),
    ("gate2", "agent7_acceptance_handler"),
    ("gate2", "agent8_rejection_feedback_composer"),
    ("agent7_acceptance_handler", "agent9_dashboard_service"),
    ("agent9_dashboard_service", "agent10_success_predictor"),
    ("agent10_success_predictor", "end_accepted"),
    ("agent8_rejection_feedback_composer", "end_rejected"),
]


def _build_sequence(raw_agents, durations, status=None):
    """Walk the same branch logic as src/orchestration/pipeline.py to reconstruct the exact path
    this run took, inserting the (unlogged) gate/end nodes so the graph shows a complete story,
    not just the agent calls. `status` disambiguates two runs that both stop right after Agent 6
    with no Agent 7/8 yet: a real Agent-6 "inconclusive" verdict (DB status -> pmo_review, ends at
    the end_review chip) vs. a run that's genuinely just waiting on a live Manual Gate 2 decision
    (DB status stays "analysis" — see src/orchestration/pipeline.py's run_intake_to_gate2), which
    should stop at the gate2 diamond itself, not a terminal chip that hasn't happened yet."""
    seq = []
    def add(node_id, kind="agent"):
        label = AGENT_LABELS.get(node_id, NODE_POS.get(node_id, (0,0,0,0,"","·"))[5].replace("\n", " · "))
        seq.append({"id": node_id, "label": label, "duration_ms": durations.get(node_id, 0), "kind": kind})

    if "agent1_intake_parser" not in raw_agents:
        return seq  # no trace at all (shouldn't happen for a real run)
    add("agent1_intake_parser")
    if "agent2_duplicate_checker" not in raw_agents:
        add("end_incomplete", "end")
        return seq
    add("agent2_duplicate_checker")
    if "agent3_duplicate_rejection_notifier" in raw_agents:
        add("agent3_duplicate_rejection_notifier")
        add("end_dup", "end")
        return seq
    add("gate1", "gate")
    if "agent4_pmo_router" in raw_agents:
        add("agent4_pmo_router")
    if "agent5_business_impact" in raw_agents:
        add("agent5_business_impact")
    if "agent6_knowledge_crosscheck" in raw_agents:
        add("agent6_knowledge_crosscheck")
    else:
        return seq
    if "agent7_acceptance_handler" not in raw_agents and "agent8_rejection_feedback_composer" not in raw_agents:
        if status == "analysis":
            add("gate2", "gate")
            return seq
        add("end_review", "end")
        return seq
    add("gate2", "gate")
    if "agent7_acceptance_handler" in raw_agents:
        add("agent7_acceptance_handler")
        if "agent9_dashboard_service" in raw_agents:
            add("agent9_dashboard_service")
        if "agent10_success_predictor" in raw_agents:
            add("agent10_success_predictor")
        add("end_accepted", "end")
    else:
        add("agent8_rejection_feedback_composer")
        add("end_rejected", "end")
    return seq


STATUS_BANNER = {
    "accepted": ("#eaf3de", "#3b6d11", "✓ Accepted"),
    "in_progress": ("#eaf3de", "#3b6d11", "✓ Accepted — in progress"),
    "rejected": ("#fcebeb", "#a32d2d", "✗ Rejected"),
    "pmo_review": ("#faeeda", "#854f0b", "⏳ Under review — sent back to PMO"),
    "analysis": ("#e6f1fb", "#1a5a92", "⏳ In analysis"),
}

def render(project_id, replay_pace_ms=5000, redirect_to=None, resume_from=None):
    """
    resume_from: the node id (e.g. "gate2") the PMO already watched this run animate up through, in
    a PRIOR render of this same page (see run_intake_to_gate2's partial visualizer). Passed by
    scripts/demo_engine.py's resume_scenario() so the post-decision replay fast-forwards through
    the already-seen Agents 1-6/Gate 1/Gate 2 instead of replaying the whole thing from scratch —
    it continues on to Agent 7-10 (or Agent 8) at the normal pace, which is the only part that's new.
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM audit_log WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    raw_agents = [r["agent"] for r in rows]
    durations = {r["agent"]: r["duration_ms"] for r in rows}

    proj_row = conn.execute(
        "SELECT * FROM projects WHERE project_id = ? OR submission_id = ?", (project_id, project_id)
    ).fetchone()
    proj = dict(proj_row) if proj_row else {}
    status = proj.get("status", "")
    bg, fg, label = STATUS_BANNER.get(status, ("#f5f4f0", "#5f5e5a", status.title() or "Unknown"))
    reason_line = f' — {proj["rejection_reason"]}' if status == "rejected" and proj.get("rejection_reason") else ""
    status_banner = (
        f'<div id="status-banner" style="background:{bg};color:{fg};border-radius:8px;padding:12px 16px;'
        f'margin-bottom:16px;font-size:14px;font-weight:600">{label}{reason_line}</div>'
    )

    # Notifications are NOT rendered as a panel on this page anymore — the composer's right panel
    # (scripts/demo_server.py) shows them live via postMessage as replay reaches each triggering
    # step, so a second static copy here would just be a duplicate. Still queried here because the
    # notif_feed JSON below (fed to that right panel) is built from these same rows.
    notif_rows = conn.execute("SELECT * FROM notifications WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()

    # Fed to the parent composer page (scripts/demo_server.py) via postMessage as replay proceeds,
    # so a separate "notifications" panel there can show each one appearing at the exact moment its
    # triggering step finishes — not just a static end-of-run list.
    notif_feed = [
        {
            "trigger_agent": n["trigger_agent"],
            "trigger_label": AGENT_LABELS.get(n["trigger_agent"], n["trigger_agent"] or "—"),
            "recipient": n["recipient"], "channel": n["channel"],
            "subject": n["subject"], "body": n["body"],
        }
        for n in notif_rows
    ]
    notif_feed_json = json.dumps(notif_feed)

    # Original flat list — kept for the execution-log panel and the automated-time summary.
    steps = [{"agent": AGENT_LABELS.get(r["agent"], r["agent"]), "duration_ms": r["duration_ms"]} for r in rows]
    steps_json = json.dumps(steps)

    # Extended path (with virtual gate/end nodes) that drives the graph animation.
    sequence = _build_sequence(raw_agents, durations, status)
    sequence_json = json.dumps(sequence)
    redirect_json = json.dumps(redirect_to)
    resume_from_json = json.dumps(resume_from)

    # The flat `steps`/log-list array (built from raw audit_log rows above) has no "gate2" entry of
    # its own to look up like the graph's `sequence` does — gates aren't real agent calls. So work
    # out how many of those raw rows were already shown in the prior partial render by finding the
    # last row belonging to the real agent that immediately precedes Gate 2 (Agent 6), and fast-
    # forward the execution log through that many entries too, in sync with the graph.
    resume_step_count = 0
    if resume_from == "gate2":
        for idx, r in enumerate(rows):
            if r["agent"] == "agent6_knowledge_crosscheck":
                resume_step_count = idx + 1
    resume_step_count_json = json.dumps(resume_step_count)

    # SVG edges — every structural edge, dim by default; JS lights up the ones this run traversed.
    # Connect on whichever axis the two nodes are actually separated on, so lateral branches
    # (e.g. agent2 -> agent3) draw side-to-side instead of running through the node stack below.
    edge_svg = []
    for a, b in EDGES:
        ax, ay, aw, ah = NODE_POS[a][:4]
        bx, by, bw, bh = NODE_POS[b][:4]
        eid = f"edge_{a}__{b}"
        if abs(by - ay) >= abs(bx - ax):
            x1, y1 = ax, ay + ah / 2 if by > ay else ay - ah / 2
            x2, y2 = bx, by - bh / 2 if by > ay else by + bh / 2
        else:
            x1, y1 = ax + aw / 2 if bx > ax else ax - aw / 2, ay
            x2, y2 = bx - bw / 2 if bx > ax else bx + bw / 2, by
        edge_svg.append(
            f'<line id="{eid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'class="edge" marker-end="url(#arrow)"/>'
        )
    edges_svg_str = "\n".join(edge_svg)

    # Node DOM elements — box/diamond/chip per NODE_POS.
    node_divs = []
    for nid, (cx, cy, w, h, shape, label) in NODE_POS.items():
        lines = label.split("\n")
        inner = "<br>".join(lines)
        node_divs.append(
            f'<div class="node {shape}" id="node-{nid}" '
            f'style="left:{cx-w/2}px;top:{cy-h/2}px;width:{w}px;height:{h}px;">'
            f'<span>{inner}</span></div>'
        )
    nodes_html = "\n".join(node_divs)

    canvas_w = max(p[0] + p[2] for p in NODE_POS.values()) + 40
    canvas_h = max(p[1] + p[3] for p in NODE_POS.values()) + 40

    # Only set for a run that's genuinely pending a Manual Gate 2 decision (see run_scenario_to_gate2
    # in scripts/demo_engine.py) — lets a PMO watch Agents 1-6 actually run in sequence first. This
    # page never navigates itself to the Gate 2 page — that would replace the flow graph the PMO is
    # meant to keep watching. Instead it posts a message up to the parent composer, which opens the
    # decision UI in the RIGHT panel (notifications side), so making the call never interrupts the
    # view of the flow itself (see scripts/demo_server.py's message listener).
    gate2_link_html = (
        f'<button type="button" id="skip-gate2-btn" style="margin-left:auto;background:none;border:none;'
        f'font-size:13px;color:#378ADD;font-weight:600;cursor:pointer;padding:0">Show Gate 2 decision now →</button>'
        if redirect_to else ""
    )

    # Comments/Notifications pages only exist for project IDs that actually reached a point where
    # something got rendered for them (e.g. an accepted project) — cases that stop earlier (like
    # SUB-CASE9, parked mid-flow for the Gate 3 demo) never get those pages written. Linking to a
    # page that doesn't exist is a dead-end 404 for whoever's driving the demo, so only show each
    # link if its target file is actually on disk.
    _dash_dir = os.path.dirname(__file__)
    extra_nav_links = "".join(
        f'<a href="{fname}">{label}</a>'
        for fname, label in (
            (f"notifications_{project_id}.html", "Notifications"),
        )
        if os.path.exists(os.path.join(_dash_dir, fname))
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Live Execution Visualizer — {project_id}</title>
<style>
body{{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:1.5rem 2rem;color:#2a2a28}}
h3{{margin-bottom:4px}}
.nav{{font-size:12px;margin-bottom:10px}}
.nav a{{color:#378ADD;text-decoration:none;margin-right:14px}}
.nav a:hover{{text-decoration:underline}}
#topbar{{display:flex;align-items:center;gap:14px;margin-bottom:14px}}
#replay-btn{{background:#378ADD;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:14px;cursor:pointer}}
#replay-btn:hover{{background:#2c6fb3}}
#status{{font-size:13px;color:#555;font-family:monospace}}
#layout{{display:flex;gap:24px;align-items:flex-start}}
#graph-wrap{{position:relative;width:{canvas_w}px;height:{canvas_h}px;flex-shrink:0}}
svg#edges{{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}}
line.edge{{stroke:#ddd;stroke-width:2;transition:stroke .25s,stroke-width .25s}}
line.edge.lit{{stroke:#378ADD;stroke-width:3}}
line.edge.lit.done{{stroke:#639922}}
.node{{position:absolute;display:flex;align-items:center;justify-content:center;text-align:center;
  font-size:12px;line-height:1.3;border-radius:8px;background:#f5f4f0;border:1.5px solid #e5e3dc;
  color:#999;transition:background .3s,border-color .3s,color .3s;box-sizing:border-box;padding:4px}}
.node.diamond{{border-radius:0;transform:rotate(45deg)}}
.node.diamond span{{transform:rotate(-45deg);font-weight:600}}
.node.chip{{border-radius:20px;font-size:11px;font-style:italic}}
.node.active{{background:#e6f1fb;border-color:#378ADD;color:#1a1a1a;box-shadow:0 0 0 3px rgba(55,138,221,.15)}}
.node.complete{{background:#eaf3de;border-color:#639922;color:#1a1a1a}}
#log{{flex:1;min-width:280px;max-width:340px;font-size:13px}}
#log h4{{margin:0 0 8px}}
#log-list{{list-style:none;margin:0;padding:0;border-left:2px solid #e5e3dc}}
#log-list li{{padding:6px 0 6px 14px;color:#bbb;font-family:monospace;font-size:12px;border-left:2px solid transparent;margin-left:-2px}}
#log-list li.active{{color:#378ADD;border-left-color:#378ADD}}
#log-list li.complete{{color:#333;border-left-color:#639922}}
#summary{{margin-top:16px;font-size:13px;color:#555}}
.legend{{margin-top:10px;font-size:11px;color:#888;display:flex;gap:16px}}
.legend span{{display:inline-flex;align-items:center;gap:5px}}
.sw{{width:10px;height:10px;border-radius:3px;display:inline-block}}
</style></head><body>
<div class="nav"><a href="/" target="_top">← Composer</a>
{extra_nav_links}</div>
<h3>Live Execution Visualizer — {project_id}</h3>
{status_banner}
<div id="topbar">
  <button id="replay-btn" onclick="startReplay()">▶ Replay</button>
  <span id="status">Ready.</span>
  {gate2_link_html}
</div>
<div id="layout">
  <div id="graph-wrap">
    <svg id="edges" viewBox="0 0 {canvas_w} {canvas_h}">
      <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#bbb"/></marker></defs>
      {edges_svg_str}
    </svg>
    {nodes_html}
  </div>
  <div id="log">
    <h4>Execution log</h4>
    <ul id="log-list"></ul>
    <div class="legend">
      <span><i class="sw" style="background:#378ADD"></i>running</span>
      <span><i class="sw" style="background:#639922"></i>done</span>
      <span><i class="sw" style="background:#e5e3dc"></i>not on this path</span>
    </div>
  </div>
</div>
<div id="summary"></div>
<script>
const sequence = {sequence_json};
const steps = {steps_json};
const notifFeed = {notif_feed_json};
const pace = {replay_pace_ms};
const redirectTo = {redirect_json};
const resumeFrom = {resume_from_json};
const resumeStepCount = {resume_step_count_json};
// Index of the last node already shown in a prior partial render (see render_visualizer.py's
// resume_from docstring) — everything up to and including it fast-forwards with no delay below;
// -1 (not found / not set) means play the whole thing at normal pace, as usual.
const resumeIndex = resumeFrom ? sequence.findIndex(n => n.id === resumeFrom) : -1;

function tellParent(msg) {{
  try {{ window.parent.postMessage(msg, '*'); }} catch (e) {{}}
}}

// Never navigates THIS page — the composer (scripts/demo_server.py) opens the Gate 2 decision UI
// in the right panel instead, so the flow graph here stays visible the whole time a PMO is
// deciding. Also wired to the "Show Gate 2 decision now" button for anyone who doesn't want to
// wait out the replay.
//
// redirectTo is a bare filename (e.g. "gate2_SUB-0001.html") — relative to THIS page's own URL
// (/dashboard/visualizer_...), which is why it worked fine back when this page navigated itself
// to it directly. Posted up to the parent composer's right panel instead, a bare relative path
// resolves against the PARENT page's URL ("/") rather than "/dashboard/" and 404s — hence the
// absolute "/dashboard/" prefix here.
function showGate2Decision() {{
  if (redirectTo) tellParent({{type: 'gate2_pending', gate2_url: '/dashboard/' + redirectTo}});
}}
const skipBtn = document.getElementById('skip-gate2-btn');
if (skipBtn) skipBtn.addEventListener('click', showGate2Decision);

const logList = document.getElementById('log-list');
steps.forEach((s, i) => {{
  const li = document.createElement('li');
  li.id = 'log-' + i;
  li.textContent = s.agent;
  logList.appendChild(li);
}});

function resetGraph() {{
  document.querySelectorAll('.node').forEach(n => n.classList.remove('active','complete'));
  document.querySelectorAll('.edge').forEach(e => e.classList.remove('lit','done'));
  document.querySelectorAll('#log-list li').forEach(li => li.classList.remove('active','complete'));
  document.getElementById('summary').innerText = '';
}}

function playGraph(i) {{
  if (i > 0) {{
    const prevId = sequence[i-1].id;
    const prevEl = document.getElementById('node-' + prevId);
    if (prevEl) {{ prevEl.classList.remove('active'); prevEl.classList.add('complete'); }}
    if (i < sequence.length) {{
      const edgeEl = document.getElementById('edge_' + prevId + '__' + sequence[i].id);
      if (edgeEl) {{ edgeEl.classList.remove('lit'); edgeEl.classList.add('lit','done'); }}
    }}
    // The step that just finished may have triggered a notification — surface it now, in sync
    // with the graph, rather than only in the static list at the top of this page.
    notifFeed.filter(n => n.trigger_agent === prevId).forEach(n => tellParent({{type: 'notification', notif: n}}));
  }}
  if (i >= sequence.length) {{
    if (redirectTo) {{
      document.getElementById('status').innerText = 'Done. Awaiting a Gate 2 decision — see the right panel →';
      setTimeout(() => showGate2Decision(), 800);
    }} else {{
      document.getElementById('status').innerText = 'Done.';
    }}
    return;
  }}
  const node = sequence[i];
  const el = document.getElementById('node-' + node.id);
  if (el) {{ el.classList.add('active'); }}
  if (i > 0) {{
    const edgeEl = document.getElementById('edge_' + sequence[i-1].id + '__' + node.id);
    if (edgeEl) edgeEl.classList.add('lit');
  }}
  document.getElementById('status').innerText = 'Running: ' + node.label.replace('\\n', ' ');
  // Already-seen nodes (0..resumeIndex, from a prior partial render) fast-forward with no delay;
  // the first genuinely new node onward (e.g. Agent 7 right after a Gate 2 accept) plays at the
  // normal pace, same as a from-scratch run.
  const delay = (i <= resumeIndex) ? 0 : pace;
  setTimeout(() => playGraph(i+1), delay);
}}

function playStep(i) {{
  if (i > 0) {{
    const prev = document.getElementById('log-' + (i-1));
    if (prev) {{ prev.classList.remove('active'); prev.classList.add('complete'); }}
  }}
  if (i >= steps.length) {{
    document.getElementById('summary').innerText =
      'Automated steps total: ' + steps.reduce((a,s)=>a+s.duration_ms,0) + 'ms (mock-mode timings — real API calls will reflect actual model latency per SLA targets).';
    return;
  }}
  const li = document.getElementById('log-' + i);
  if (li) {{
    li.classList.add('active');
    li.textContent = steps[i].agent + ' — ' + steps[i].duration_ms + 'ms';
  }}
  // Same fast-forward as playGraph, kept in sync: entries before resumeStepCount were already in
  // the log during the prior partial render.
  const delay = (i < resumeStepCount) ? 0 : pace;
  setTimeout(() => playStep(i+1), delay);
}}

function startReplay() {{
  resetGraph();
  tellParent({{type: 'reset'}});
  document.getElementById('status').innerText = 'Running…';
  playGraph(0);
  playStep(0);
}}
startReplay();
</script>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"visualizer_{project_id}.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, len(steps)

if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "PRJ-2026-0791"
    path, n = render(pid)
    print(f"rendered {path} with {n} steps")
