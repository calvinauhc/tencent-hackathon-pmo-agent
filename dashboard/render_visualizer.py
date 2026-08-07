"""
Live Execution Visualizer, replay mode (§9.1, Phase 4.2 — replay only, live polling deferred per
BUILD-TASKS.md). Reads real audit_log rows for one project and replays them client-side at a fixed
pace via JS — a directed graph of the actual 1-10 pipeline (§2), with the real path this submission
took lighting up node-by-node and edge-by-edge, CrewAI-flow style, plus a scrolling execution log.
Only the nodes/edges this specific run actually touched light up; the rest of the graph stays
dimmed to show the paths that existed but weren't taken (duplicate-reject, misaligned-reject, etc).

Layout: horizontal snake / S-curve (3 nodes per row, rows alternate L→R and R→L), inspired by
step-by-step process flow diagrams — the main trunk flows like a ribbon, exit branches hang below
each junction node.
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

# ─── Snake-layout constants ───────────────────────────────────────────────────
# The main pipeline trunk flows in a horizontal snake: 3 nodes per row,
# rows alternate left-to-right then right-to-left, connected by a U-turn
# at each row end (like the reference image).
#
# Row 0 (L→R): Agent1 → Agent2 → Gate1
# Row 1 (R→L): Agent6 → Agent5 → Agent4          (U-turn connector after Gate1)
# Row 2 (L→R): Agent7 → Agent9 → Agent10
# Row 3 (R→L): end_accepted  (last chip, right-aligned end)
#
# Exit branches hang BELOW the junction node (not sideways), keeping
# the snake ribbon readable on screen.

NODE_W   = 160   # box width
NODE_H   = 56    # box height
GATE_S   = 80    # diamond "radius" (square side before rotation)
CHIP_H   = 38    # terminal chip height
COL_GAP  = 60    # horizontal gap between node centres in a row
BRANCH_DY = 100  # extra Y below a row centre for exit-branch chips/nodes

# Per-row Y centres — non-uniform gaps so branches never overlap the next row
# Row 0→1 gap = 250  (needs room for: end_dup = BRANCH_DY+NODE_H+30+CHIP_H/2 = 214 → safe)
# Row 1→2 gap = 175  (end_review = BRANCH_DY+CHIP_H/2 = 119 below row1 → safe)
# Row 2→3 gap = 200  (agent8+end_rejected = BRANCH_DY+NODE_H+30+CHIP_H/2 = 214 — same as row0)
ROW_Y = [110, 360, 535, 780]

# Node centre X values (3 columns)
COL_X = [120, 120 + NODE_W + COL_GAP, 120 + 2*(NODE_W + COL_GAP)]  # ≈ 120, 340, 560

def _cx(col): return COL_X[col]
def _cy(row): return ROW_Y[row]

# (cx, cy, w, h, shape, label)
NODE_POS = {
    # ── Row 0 L→R ──────────────────────────────────────────────────────────
    "agent1_intake_parser":              (_cx(0), _cy(0), NODE_W, NODE_H, "box",     "Agent 1\nIntake Parser"),
    "agent2_duplicate_checker":          (_cx(1), _cy(0), NODE_W, NODE_H, "box",     "Agent 2\nDuplicate Checker"),
    "gate1":                             (_cx(2), _cy(0), GATE_S, GATE_S, "diamond", "Gate 1\nProceed"),

    # ── Row 1 R→L: Gate1 → Agent4 → Agent5 → Agent6 → Gate2 ───────────────
    "agent4_pmo_router":                 (_cx(2), _cy(1), NODE_W, NODE_H, "box",     "Agent 4\nPMO Router / Ack"),
    "agent5_business_impact":            (_cx(1), _cy(1), NODE_W, NODE_H, "box",     "Agent 5\nBusiness Impact"),
    "agent6_knowledge_crosscheck":       (_cx(0), _cy(1), NODE_W, NODE_H, "box",     "Agent 6\nKnowledge Cross-Check"),

    # ── Row 2 L→R ──────────────────────────────────────────────────────────
    "gate2":                             (_cx(0), _cy(2), GATE_S, GATE_S, "diamond", "Gate 2\nPMO Decision"),
    "agent7_acceptance_handler":         (_cx(1), _cy(2), NODE_W, NODE_H, "box",     "Agent 7\nAcceptance Handler"),
    "agent9_dashboard_service":          (_cx(2), _cy(2), NODE_W, NODE_H, "box",     "Agent 9\nDashboard Publish"),

    # ── Row 3 R→L ──────────────────────────────────────────────────────────
    "agent10_success_predictor":         (_cx(2), _cy(3), NODE_W, NODE_H, "box",     "Agent 10\nSuccess Predictor"),
    "end_accepted":                      (_cx(1), _cy(3), NODE_W, CHIP_H, "chip",    "✓ Accepted"),

    # ── Exit branches (hang below their junction) ───────────────────────────
    # Below Agent 1 (row 0 col 0) — incomplete rejection chip
    "end_incomplete":                    (_cx(0), _cy(0) + BRANCH_DY, NODE_W, CHIP_H, "chip", "Rejected\nIncomplete info"),
    # Below Agent 2 (row 0 col 1) — duplicate path
    "agent3_duplicate_rejection_notifier": (_cx(1), _cy(0) + BRANCH_DY, NODE_W, NODE_H, "box", "Agent 3\nDuplicate Reject Notify"),
    "end_dup":                           (_cx(1), _cy(0) + BRANCH_DY + NODE_H + 30, NODE_W, CHIP_H, "chip", "Rejected\nDuplicate"),
    # Above Agent 6 (row 1 col 0) — inconclusive/under review exit, sits above Agent 6
    "end_review":                        (_cx(0), _cy(1) - BRANCH_DY, NODE_W, CHIP_H, "chip", "Under Review\nInconclusive"),
    # Below Gate 2 (row 2 col 0) — rejection path
    "agent8_rejection_feedback_composer": (_cx(0), _cy(2) + BRANCH_DY, NODE_W, NODE_H, "box", "Agent 8\nRejection Feedback"),
    "end_rejected":                      (_cx(0), _cy(2) + BRANCH_DY + NODE_H + 30, NODE_W, CHIP_H, "chip", "✗ Rejected"),
}

# Main trunk edges (snake ribbon) + exit-branch edges
EDGES = [
    # Row 0 trunk (L→R)
    ("agent1_intake_parser",        "agent2_duplicate_checker"),
    ("agent2_duplicate_checker",    "gate1"),
    # U-turn: Gate1 (col2 row0) → Agent4 (col2 row1) — straight down same column
    ("gate1",                       "agent4_pmo_router"),
    # Row 1 trunk (R→L): Agent4 → Agent5 → Agent6
    ("agent4_pmo_router",           "agent5_business_impact"),
    ("agent5_business_impact",      "agent6_knowledge_crosscheck"),
    # U-turn: Agent6 (col0 row1) → Gate2 (col0 row2) — straight down same column
    ("agent6_knowledge_crosscheck", "gate2"),
    # Row 2 trunk (L→R)
    ("gate2",                       "agent7_acceptance_handler"),
    ("agent7_acceptance_handler",   "agent9_dashboard_service"),
    # U-turn: Agent9 (col2 row2) → Agent10 (col2 row3) — straight down
    ("agent9_dashboard_service",    "agent10_success_predictor"),
    # Row 3 trunk (R→L)
    ("agent10_success_predictor",   "end_accepted"),

    # Exit branches (vertical drops)
    ("agent1_intake_parser",        "end_incomplete"),
    ("agent2_duplicate_checker",    "agent3_duplicate_rejection_notifier"),
    ("agent3_duplicate_rejection_notifier", "end_dup"),
    ("agent6_knowledge_crosscheck", "end_review"),
    ("gate2",                       "agent8_rejection_feedback_composer"),
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

    notif_rows = conn.execute("SELECT * FROM notifications WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()

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

    steps = [{"agent": AGENT_LABELS.get(r["agent"], r["agent"]), "duration_ms": r["duration_ms"]} for r in rows]
    steps_json = json.dumps(steps)

    sequence = _build_sequence(raw_agents, durations, status)
    sequence_json = json.dumps(sequence)
    redirect_json = json.dumps(redirect_to)
    resume_from_json = json.dumps(resume_from)

    resume_step_count = 0
    if resume_from == "gate2":
        for idx, r in enumerate(rows):
            if r["agent"] == "agent6_knowledge_crosscheck":
                resume_step_count = idx + 1
    resume_step_count_json = json.dumps(resume_step_count)

    # ── SVG edges ────────────────────────────────────────────────────────────
    # For the snake trunk (same-column U-turns), draw a straight vertical line.
    # For same-row horizontal hops, draw a straight horizontal line.
    # For exit branches (vertical drop), draw straight vertical line.
    # A curved elbow path is used only for diagonal connections.
    edge_svg = []
    for a, b in EDGES:
        ax, ay, aw, ah = NODE_POS[a][:4]
        bx, by, bw, bh = NODE_POS[b][:4]
        eid = f"edge_{a}__{b}"

        dx = abs(bx - ax)
        dy = abs(by - ay)

        if dx < 20:
            # Vertical connection (same column — U-turn or exit branch)
            x1, y1 = ax, ay + ah / 2
            x2, y2 = bx, by - bh / 2
            edge_svg.append(
                f'<line id="{eid}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'class="edge" marker-end="url(#arrow)"/>'
            )
        elif dy < 20:
            # Horizontal connection (same row)
            if bx > ax:
                x1, y1 = ax + aw / 2, ay
                x2, y2 = bx - bw / 2, by
            else:
                x1, y1 = ax - aw / 2, ay
                x2, y2 = bx + bw / 2, by
            edge_svg.append(
                f'<line id="{eid}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'class="edge" marker-end="url(#arrow)"/>'
            )
        else:
            # Diagonal / elbow — use two-segment path (right-angle elbow)
            if bx > ax:
                sx, sy = ax + aw / 2, ay
                ex, ey = bx - bw / 2, by
            else:
                sx, sy = ax - aw / 2, ay
                ex, ey = bx + bw / 2, by
            mid_x = (sx + ex) / 2
            edge_svg.append(
                f'<path id="{eid}" d="M{sx:.1f},{sy:.1f} L{mid_x:.1f},{sy:.1f} L{mid_x:.1f},{ey:.1f} L{ex:.1f},{ey:.1f}" '
                f'class="edge" fill="none" marker-end="url(#arrow)"/>'
            )

    # ── Snake ribbon background path ─────────────────────────────────────────
    # Draw a thick rounded-rect ribbon behind the trunk to make the S-curve
    # visually obvious (similar to the green/blue stripe in the reference image).
    # The ribbon follows: row0 (L→R), down col2, row1 (R→L), down col0, row2 (L→R),
    # down col2, row3 (R→L).
    ribbon_pts = [
        # Row 0: left edge of col0 → right edge of col2
        (COL_X[0] - NODE_W//2, ROW_Y[0]),
        (COL_X[2] + NODE_W//2, ROW_Y[0]),
        # Down col2 to row1
        (COL_X[2] + NODE_W//2, ROW_Y[1]),
        (COL_X[0] - NODE_W//2, ROW_Y[1]),
        # Down col0 to row2
        (COL_X[0] - NODE_W//2, ROW_Y[2]),
        (COL_X[2] + NODE_W//2, ROW_Y[2]),
        # Down col2 to row3
        (COL_X[2] + NODE_W//2, ROW_Y[3]),
        (COL_X[0] - NODE_W//2, ROW_Y[3]),
    ]
    rh = NODE_H + 16  # ribbon height (a bit taller than nodes)
    ribbon_segs = []
    # Row 0 band
    ribbon_segs.append(
        f'<rect x="{COL_X[0]-NODE_W//2-8}" y="{ROW_Y[0]-rh//2}" '
        f'width="{COL_X[2]+NODE_W//2 - (COL_X[0]-NODE_W//2) + 16}" height="{rh}" '
        f'rx="34" fill="#378ADD" opacity="0.10"/>'
    )
    # Row 1 band
    ribbon_segs.append(
        f'<rect x="{COL_X[0]-NODE_W//2-8}" y="{ROW_Y[1]-rh//2}" '
        f'width="{COL_X[2]+NODE_W//2 - (COL_X[0]-NODE_W//2) + 16}" height="{rh}" '
        f'rx="34" fill="#378ADD" opacity="0.10"/>'
    )
    # Row 2 band
    ribbon_segs.append(
        f'<rect x="{COL_X[0]-NODE_W//2-8}" y="{ROW_Y[2]-rh//2}" '
        f'width="{COL_X[2]+NODE_W//2 - (COL_X[0]-NODE_W//2) + 16}" height="{rh}" '
        f'rx="34" fill="#378ADD" opacity="0.10"/>'
    )
    # Row 3 band
    ribbon_segs.append(
        f'<rect x="{COL_X[0]-NODE_W//2-8}" y="{ROW_Y[3]-rh//2}" '
        f'width="{COL_X[2]+NODE_W//2 - (COL_X[0]-NODE_W//2) + 16}" height="{rh}" '
        f'rx="34" fill="#378ADD" opacity="0.10"/>'
    )
    # Vertical connectors between rows (U-turns)
    vconn_w = NODE_W + 16
    # right side (col2): row0→row1
    ribbon_segs.append(
        f'<rect x="{COL_X[2]-vconn_w//2}" y="{ROW_Y[0]+rh//2-4}" '
        f'width="{vconn_w}" height="{ROW_Y[1]-ROW_Y[0]-rh+8}" '
        f'fill="#378ADD" opacity="0.10"/>'
    )
    # left side (col0): row1→row2
    ribbon_segs.append(
        f'<rect x="{COL_X[0]-vconn_w//2}" y="{ROW_Y[1]+rh//2-4}" '
        f'width="{vconn_w}" height="{ROW_Y[2]-ROW_Y[1]-rh+8}" '
        f'fill="#378ADD" opacity="0.10"/>'
    )
    # right side (col2): row2→row3
    ribbon_segs.append(
        f'<rect x="{COL_X[2]-vconn_w//2}" y="{ROW_Y[2]+rh//2-4}" '
        f'width="{vconn_w}" height="{ROW_Y[3]-ROW_Y[2]-rh+8}" '
        f'fill="#378ADD" opacity="0.10"/>'
    )
    ribbon_svg = "\n".join(ribbon_segs)

    edges_svg_str = "\n".join(edge_svg)

    # ── Node DOM elements ─────────────────────────────────────────────────────
    node_divs = []
    for nid, (cx, cy, w, h, shape, lbl) in NODE_POS.items():
        lines = lbl.split("\n")
        inner = "<br>".join(lines)
        node_divs.append(
            f'<div class="node {shape}" id="node-{nid}" '
            f'style="left:{cx-w/2:.1f}px;top:{cy-h/2:.1f}px;width:{w}px;height:{h}px;">'
            f'<span>{inner}</span></div>'
        )
    nodes_html = "\n".join(node_divs)

    canvas_w = max(p[0] + p[2]//2 for p in NODE_POS.values()) + 60
    canvas_h = max(p[1] + p[3]//2 for p in NODE_POS.values()) + 60

    gate2_link_html = (
        f'<button type="button" id="skip-gate2-btn" style="margin-left:auto;background:none;border:none;'
        f'font-size:13px;color:#378ADD;font-weight:600;cursor:pointer;padding:0">Show Gate 2 decision now →</button>'
        if redirect_to else ""
    )

    _dash_dir = os.path.dirname(__file__)
    extra_nav_links = "".join(
        f'<a href="{fname}">{lnk_label}</a>'
        for fname, lnk_label in (
            (f"notifications_{project_id}.html", "Notifications"),
        )
        if os.path.exists(os.path.join(_dash_dir, fname))
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Live Execution Visualizer — {project_id}</title>
<style>
body{{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:1.5rem 2rem;color:#2a2a28;background:#fafaf8}}
h3{{margin-bottom:4px}}
.nav{{font-size:12px;margin-bottom:10px}}
.nav a{{color:#378ADD;text-decoration:none;margin-right:14px}}
.nav a:hover{{text-decoration:underline}}
#topbar{{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}}
#replay-btn{{background:#378ADD;color:#fff;border:none;border-radius:6px;padding:8px 18px;font-size:14px;cursor:pointer;font-weight:600}}
#replay-btn:hover{{background:#2c6fb3}}
#status{{font-size:13px;color:#555;font-family:monospace}}
/* ── Snake diagram wrapper ── */
#main-wrap{{display:flex;gap:28px;align-items:flex-start}}
#graph-wrap{{position:relative;flex-shrink:0}}
svg#edges{{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible}}
line.edge,path.edge{{stroke:#ccc;stroke-width:2;transition:stroke .25s,stroke-width .25s;fill:none}}
line.edge.lit,path.edge.lit{{stroke:#378ADD;stroke-width:3}}
line.edge.lit.done,path.edge.lit.done{{stroke:#639922}}
/* ── Node cards ── */
.node{{position:absolute;display:flex;align-items:center;justify-content:center;text-align:center;
  font-size:11px;line-height:1.35;border-radius:10px;
  background:#fff;border:2px solid #e0ddd5;
  color:#aaa;transition:background .3s,border-color .3s,color .3s,box-shadow .3s;
  box-sizing:border-box;padding:6px 8px;
  box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.node .step-num{{display:block;font-size:9px;font-weight:700;letter-spacing:.05em;
  color:#bbb;margin-bottom:2px;text-transform:uppercase}}
.node.diamond{{border-radius:0;transform:rotate(45deg);background:#fff5e0;border-color:#e8c96a}}
.node.diamond span{{transform:rotate(-45deg);font-weight:700;font-size:11px}}
.node.chip{{border-radius:20px;font-size:10px;font-style:italic;background:#f0f0ec;border-color:#ddd}}
.node.active{{background:#e6f1fb;border-color:#378ADD;color:#1a1a1a;
  box-shadow:0 0 0 4px rgba(55,138,221,.18),0 2px 8px rgba(55,138,221,.12)}}
.node.diamond.active{{background:#e6f1fb;border-color:#378ADD}}
.node.complete{{background:#eaf3de;border-color:#639922;color:#2a2a28;
  box-shadow:0 1px 4px rgba(99,153,34,.10)}}
.node.diamond.complete{{background:#eaf3de;border-color:#639922}}
/* ── Execution log panel ── */
#log{{flex:1;min-width:240px;max-width:300px;font-size:13px}}
#log h4{{margin:0 0 10px;font-size:13px;color:#444}}
#log-list{{list-style:none;margin:0;padding:0;border-left:2px solid #e5e3dc}}
#log-list li{{padding:5px 0 5px 14px;color:#bbb;font-family:monospace;font-size:11px;
  border-left:2px solid transparent;margin-left:-2px;transition:color .2s}}
#log-list li.active{{color:#378ADD;border-left-color:#378ADD}}
#log-list li.complete{{color:#444;border-left-color:#639922}}
#summary{{margin-top:14px;font-size:12px;color:#777;line-height:1.5}}
.legend{{margin-top:12px;font-size:11px;color:#999;display:flex;gap:16px;flex-wrap:wrap}}
.legend span{{display:inline-flex;align-items:center;gap:5px}}
.sw{{width:10px;height:10px;border-radius:3px;display:inline-block}}
/* ── Row direction labels ── */
.row-label{{position:absolute;font-size:9px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:#aaa;pointer-events:none}}
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
<div id="main-wrap">
  <div id="graph-wrap" style="width:{canvas_w}px;height:{canvas_h}px;">
    <svg id="edges" viewBox="0 0 {canvas_w} {canvas_h}">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#bbb"/>
        </marker>
        <marker id="arrow-lit" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#378ADD"/>
        </marker>
        <marker id="arrow-done" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#639922"/>
        </marker>
      </defs>
      {ribbon_svg}
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
      <span><i class="sw" style="background:#e5e3dc"></i>not on path</span>
    </div>
    <div id="summary"></div>
  </div>
</div>
<script>
const sequence = {sequence_json};
const steps = {steps_json};
const notifFeed = {notif_feed_json};
const pace = {replay_pace_ms};
const redirectTo = {redirect_json};
const resumeFrom = {resume_from_json};
const resumeStepCount = {resume_step_count_json};
const resumeIndex = resumeFrom ? sequence.findIndex(n => n.id === resumeFrom) : -1;

function tellParent(msg) {{
  try {{ window.parent.postMessage(msg, '*'); }} catch (e) {{}}
}}

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
