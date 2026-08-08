"""
UI PREVIEW ONLY — "Executive Precision" theme (../1786153757876_DESIGN.md). Not wired into
demo_server.py/dashboard/, not committed to git (holding per explicit instruction until sign-off).

v3 — full restructure per feedback round 3, v4 — live-transaction rewrite per feedback round 4:
  - Dashboard: 4 metric cards (Total Projects / Portfolio Value / Approved Rate / Avg Success) +
    4 real distribution panels (Status / CAPEX Funding Coverage / Predictive Portfolio Health /
    Portfolio Value by BU) — this is TECH-SPEC.md §9's own "topline" design (metric cards +
    distribution panels), which is where the "4 measurable criteria" the user meant actually live.
  - Projects tab: Needs Attention (real pending Gate 3 change request) / Active / Queued, the
    latter two collapsible.
  - Agent tab -> Agent Settings: all 13 agents + real tunables from src/shared/config.py.
  - Documents tab: real data/pvp.md, playbook.md, regulatory.md, + a Governance tab sourced from
    TECH-SPEC.md §8.2 (the only real governance/guardrails text in this repo) — now with a real
    "+" button to add another document (session-scoped, not written to disk).
  - Live Workflow: real case 1-7 switcher, each with an **Execute** button that actually replays
    dashboard/render_visualizer.py's real audit-log-backed animation for that case (the same file
    already built for §9.1 — it already runs a live node/edge replay and already postMessages a
    real notification the instant each agent step completes; nothing new had to be invented here,
    just reused). Iframes are lazy (`data-src`, no `src`) so nothing auto-plays on page load —
    execution only happens when the PMO clicks Execute.
  - Mail is no longer a static dump: Inbox/Sent start EMPTY and are populated live, in real time,
    by that same postMessage stream as each case executes — a message lands in Inbox if its real
    `recipient` is "PMO Team", otherwise Sent, tagged with whichever case is currently running, with
    a bubble/badge animation on arrival. Draft (Case 6's real PMO/stakeholder Gate 2 comments) fires
    the same way once Case 6's replay reports `{type:'done'}` (a small, real addition to
    render_visualizer.py's own tellParent() calls — it already sent 'notification'/'reset', 'done'
    was the one signal missing). Delete stays an honest empty state. This directly answers "the
    draft/sent folders are static and not dependable with the transactions" — they're now driven by
    the actual execution, not a pre-baked dump.
  - Support (sidebar footer) now has real content: two contacts, Calvin and Miller, at their real
    @agentai.com.sg addresses.
  - "Initiate project update" gap: real worked example — submit_project_update("PRJ-2026-0791",
    "unfavorable") actually run against the live DB, producing one real pending Gate 3 change
    request, surfaced in Needs Attention. Every other Active Projects row gets a "Flag for review"
    button that explains (real, not fabricated) what would happen, since a static preview can't
    execute Agent 11/12 on an arbitrary row.
  - Single showView(key) function drives ALL navigation (sidebar nav, mail folders, topbar tabs,
    support) — one content area, one source of truth, so switching feels seamless instead of
    stacking special cases.

Run: python3 "Design file/ui_preview/build_dashboard_preview.py"   (from the Tencent Hackathon/ root)
Output: dashboard_preview.html in this same folder. Open directly in a browser.
"""
import sys, os, json, html as html_lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import demo_engine as de
from src.db.repositories import (
    get_active_projects, get_gate2_queue, get_latest_agent_payload, get_recent_notifications,
    get_comments, write_comment, get_pending_change_requests, get_project_by_ref,
)
from src.agents.agent10_success_predictor import predict_or_monitor
from src.shared import config as cfg
from demo_engine import UPDATE_BODY_PLACEHOLDER, FREEFORM_BODY_PLACEHOLDER, SCENARIO_META, SCENARIO_ORDER
# Reusing dashboard/render_visualizer.py's own real layout + branch-reconstruction logic directly —
# same NODE_POS/EDGES the production visualizer draws, same _build_sequence() that walks the real
# audit_log branch logic — rather than re-deriving a second, possibly-diverging copy of either.
from dashboard.render_visualizer import (
    NODE_POS as VIZ_NODE_POS, EDGES as VIZ_EDGES, AGENT_LABELS as VIZ_AGENT_LABELS,
    _build_sequence as viz_build_sequence,
)

OUT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.join(OUT_DIR, "..", "..")
esc = html_lib.escape

# ---------------------------------------------------------------------------
# 1. Real data gathering.
#    a) Run cases 2-7 first (each is a fresh-seeded run — capture its artifacts before the next
#       case wipes the DB). b) Run case 1 LAST so the final live DB reflects case 1's outcome.
#    c) Apply one real post-acceptance update (the "unfavorable" CHANGE_DEMO_PAYLOAD) against
#       case 1's accepted project, producing one genuine pending Gate 3 change request — this is
#       the real example behind "initiate a project update that needs PMO assessment."
# ---------------------------------------------------------------------------
per_case = {}
case6_comments = []  # real PMO/stakeholder Gate 2 comments — fed into Draft live when Case 6 reaches Gate 2

def _fetch_sequence_and_notifs(conn_i, result_id, proj):
    """Same multi-id audit_log/notifications fetch dashboard/render_visualizer.py's render() does,
    so the inline graph below plays back exactly the same real steps that file's standalone replay
    would — just rendered in THIS document instead of a nested iframe (the iframe approach turned
    out unreliable: some browsers won't paint a file:// iframe's content inside a file:// parent
    page at all, so "Running…" would show but the graph never appeared, and no postMessage ever
    fired either — which also explains why Mail never got the notification. Same-document JS has
    no such restriction.)."""
    sub_id = proj.get("submission_id") or result_id
    proj_id_db = proj.get("project_id") or result_id
    ids_to_fetch = list({result_id, sub_id, proj_id_db} - {None, ""})
    placeholders = ",".join("?" * len(ids_to_fetch))
    rows = conn_i.execute(
        f"SELECT * FROM audit_log WHERE project_id IN ({placeholders}) ORDER BY id", ids_to_fetch
    ).fetchall()
    raw_agents = [r["agent"] for r in rows]
    durations = {r["agent"]: r["duration_ms"] for r in rows}
    sequence = viz_build_sequence(raw_agents, durations, proj.get("status", ""))
    notif_rows = conn_i.execute(
        f"SELECT * FROM notifications WHERE project_id IN ({placeholders}) ORDER BY id", ids_to_fetch
    ).fetchall()
    notifications = [{
        "trigger_agent": n["trigger_agent"],
        "trigger_label": VIZ_AGENT_LABELS.get(n["trigger_agent"], n["trigger_agent"] or "—"),
        "recipient": n["recipient"], "channel": n["channel"],
        "subject": n["subject"], "body": n["body"],
    } for n in notif_rows]
    return sequence, notifications

def _capture_case(key, run_result):
    conn_i = de.get_connection()
    result_id = run_result["result_id"]
    proj = get_project_by_ref(conn_i, result_id) or {}
    sequence, notifications = _fetch_sequence_and_notifs(conn_i, result_id, proj)
    per_case[key] = {
        "num": int(key.split("_")[0]),
        "key": key,
        "title": SCENARIO_META[key]["title"],
        "outcome": SCENARIO_META[key]["outcome"],
        "project_name": proj.get("project_name", "(unknown)"),
        "final_status": run_result["trace"].get("final_status", proj.get("status", "—")),
        "sequence": sequence,
        "notifications": notifications,
    }

# Cases 3 (misaligned), 4 (inconclusive), and 6 (aligned, but a stakeholder flags a concern) all
# reach a real Gate 2 decision point rather than auto-resolving, so — per explicit request — their
# Live Workflow panes stop at Gate 2 and let the PMO actually choose Proceed / Reject / Hold, the
# same way the Case 7/8 post-acceptance panels already do. Each branch below is a REAL, separately
# resumed pipeline run (run_intake_to_gate2 then resume_after_gate2, via demo_engine's own
# run_scenario_to_gate2()/resume_scenario() — the exact functions the in-browser composer uses),
# not a fabricated one; two full fresh runs are needed (not one) because resuming a decision
# actually commits it, so it can't be replayed both ways from a single seed.
GATE2_DECISION_KEYS = {
    "3_rejected_misaligned_business_direction",
    "4_under_review_unknown_regulatory_risk",
    "6_change_request_stakeholder_flag",
}
CASE6_STAKEHOLDER_COMMENTS = [
    {"author": "Priya Sharma", "role": "pmo", "body": "Accept — confirm data handling plan before launch.",
     "is_flagged_concern": False, "linked_gate": "gate2"},
    {"author": "Wei Ling Tan", "role": "regulatory",
     "body": "This touches EU customer data — confirm a GDPR review is scheduled before go-live.",
     "is_flagged_concern": True, "linked_gate": None},
]
CASE6_GDPR_CONCERN = CASE6_STAKEHOLDER_COMMENTS[1]["body"]

def _gate2_decision_case(key, accept_override_reason=None, reject_override_reason=None, with_stakeholder_comments=False):
    # Branch A — Reject. Cases 3/4 fall back to the real default_gate2_rejection_reason() (Agent-6-
    # citation-grounded); case 6 passes an explicit override_reason that quotes the actual flagged
    # stakeholder comment rather than the generic "PMO rejected at Gate 2" fallback.
    rA = de.run_scenario_to_gate2(key)
    connA = de.get_connection()
    prefix_proj = get_project_by_ref(connA, rA["visualizer_id"]) or {}
    prefix_seq, prefix_notifs = _fetch_sequence_and_notifs(connA, rA["visualizer_id"], prefix_proj)
    comments = []
    if with_stakeholder_comments:
        for c in CASE6_STAKEHOLDER_COMMENTS:
            write_comment(connA, rA["visualizer_id"], c["author"], c["role"], c["body"],
                          is_flagged_concern=c["is_flagged_concern"], linked_gate=c["linked_gate"])
        comments = get_comments(connA, rA["visualizer_id"])
    resumedA = de.resume_scenario(rA["project"], rA["trace"], "reject", scenario_key=key,
                                   override_reason=reject_override_reason)
    connA = de.get_connection()
    full_seqA, full_notifsA = _fetch_sequence_and_notifs(
        connA, resumedA["result_id"], get_project_by_ref(connA, resumedA["result_id"]) or {})
    reject_tail = full_seqA[len(prefix_seq):]
    reject_tail_notifs = full_notifsA[len(prefix_notifs):]
    reject_reason = resumedA["trace"].get("rejection_reason", "")

    # Branch B — Accept/Proceed. Fresh reseed, separate real run.
    rB = de.run_scenario_to_gate2(key)
    connB = de.get_connection()
    if with_stakeholder_comments:
        for c in CASE6_STAKEHOLDER_COMMENTS:
            write_comment(connB, rB["visualizer_id"], c["author"], c["role"], c["body"],
                          is_flagged_concern=c["is_flagged_concern"], linked_gate=c["linked_gate"])
    resumedB = de.resume_scenario(rB["project"], rB["trace"], "accept", scenario_key=key,
                                   pmo_override_reason=accept_override_reason)
    connB = de.get_connection()
    full_seqB, full_notifsB = _fetch_sequence_and_notifs(
        connB, resumedB["result_id"], get_project_by_ref(connB, resumedB["result_id"]) or {})
    accept_tail = full_seqB[len(prefix_seq):]
    accept_tail_notifs = full_notifsB[len(prefix_notifs):]

    per_case[key] = {
        "num": int(key.split("_")[0]),
        "key": key,
        "title": SCENARIO_META[key]["title"],
        "outcome": SCENARIO_META[key]["outcome"],
        "project_name": prefix_proj.get("project_name", "(unknown)"),
        "final_status": "pending_gate2",
        "sequence": prefix_seq,
        "notifications": prefix_notifs,
        "gate2": {
            "comments": comments,
            "reject_tail": reject_tail, "reject_notifications": reject_tail_notifs, "reject_reason": reject_reason,
            "accept_tail": accept_tail, "accept_notifications": accept_tail_notifs,
        },
    }
    if key == "6_change_request_stakeholder_flag":
        case6_comments.extend(comments)

for key in SCENARIO_ORDER:
    if key == "1_accepted_aligned_low_capex_high_price":
        continue
    if key in GATE2_DECISION_KEYS:
        if key == "3_rejected_misaligned_business_direction":
            _gate2_decision_case(key, accept_override_reason="Board-approved strategic exception.")
        elif key == "4_under_review_unknown_regulatory_risk":
            _gate2_decision_case(key, accept_override_reason="Board-approved strategic exception.")
        elif key == "6_change_request_stakeholder_flag":
            _gate2_decision_case(key, reject_override_reason=f"Declining pending resolution of a flagged stakeholder concern — {CASE6_GDPR_CONCERN}",
                                  with_stakeholder_comments=True)
        continue
    _capture_case(key, de.run_scenario(key))

case1_result = de.run_scenario("1_accepted_aligned_low_capex_high_price")
_capture_case("1_accepted_aligned_low_capex_high_price", case1_result)
conn = de.get_connection()
case1_proj = get_project_by_ref(conn, case1_result["result_id"])
FLAGSHIP_PROJECT_ID = case1_proj["project_id"]  # PRJ-2026-0791

update_result = de.submit_project_update(FLAGSHIP_PROJECT_ID, "unfavorable")
conn = de.get_connection()  # re-fetch — established lesson, never trust a handle across a reseed

# Case 7 in the Live Workflow switcher (named "case8" in demo_engine.py itself, same naming the
# actual demo_server.py composer uses — only this preview's display numbering shifts) — the
# favorable payload, which auto-applies and writes one real "PMO Team" notification. Run AFTER
# "unfavorable" above: "unfavorable" evaluates to needs_authorization, which per Agent 12 (src/
# agents/agent12_change_evaluator.py) never touches the live project row while Gate 3 is pending —
# so the live row is still capex=$60,000 / Oct 2026 here, exactly matching
# CHANGE_CASE_EMAILS["favorable"]'s "previously $60,000" text. Reversing this order would still
# work but would make this case's real before/after numbers drift from its own displayed email.
case7_result = de.submit_project_update(FLAGSHIP_PROJECT_ID, "favorable")
conn = de.get_connection()
case7_notif = get_recent_notifications(conn, limit=1)[0]
CASE7_EMAIL = de.CHANGE_CASE_EMAILS["favorable"]
CHANGE_CASE_EMAILS_UNFAVORABLE = de.CHANGE_CASE_EMAILS["unfavorable"]

# ---------------------------------------------------------------------------
# 2. Final live-state queries (case 1 + the one real post-acceptance update applied on top).
# ---------------------------------------------------------------------------
active_rows = get_active_projects(conn)
predictions = {r["project_id"]: predict_or_monitor(r) for r in active_rows}
queue_rows = get_gate2_queue(conn)
needs_attention = get_pending_change_requests(conn)
all_projects = [dict(r) for r in conn.execute("SELECT * FROM projects").fetchall()]

PIPELINE_STATUSES = {"analysis", "pmo_review", "accepted", "in_progress", "completed"}
DECIDED_APPROVED = {"accepted", "in_progress", "completed"}
pipeline_projects = [p for p in all_projects if p["status"] in PIPELINE_STATUSES]

total_projects = len(all_projects)
portfolio_value = sum((p["business_impact_usd"] or 0) for p in pipeline_projects)
decided = sum(1 for p in all_projects if p["status"] in DECIDED_APPROVED or p["status"] == "rejected")
approved = sum(1 for p in all_projects if p["status"] in DECIDED_APPROVED)
approved_rate = round(100 * approved / decided) if decided else 0
scored = [predictions[r["project_id"]]["success_score"] for r in active_rows
          if predictions[r["project_id"]]["status"] == "predicted"]
avg_success = round(sum(scored) / len(scored)) if scored else None

# -- Distribution panel 1: Status Distribution --
status_buckets = {"Approved / In progress": 0, "Pending review": 0, "Cancelled": 0, "Rejected": 0}
for p in all_projects:
    s = p["status"]
    if s in ("accepted", "in_progress", "completed"):
        status_buckets["Approved / In progress"] += 1
    elif s in ("draft", "pmo_review", "analysis"):
        status_buckets["Pending review"] += 1
    elif s == "cancelled":
        status_buckets["Cancelled"] += 1
    elif s == "rejected":
        status_buckets["Rejected"] += 1

# -- Distribution panel 2: CAPEX Funding Coverage (active projects that actually need CAPEX) --
capex_buckets = {"Fully funded": 0, "Partially funded": 0, "Unfunded": 0}
for r in active_rows:
    if not r.get("capex_usd"):
        continue
    pct = r.get("capex_funded_pct") or 0
    if pct >= 100:
        capex_buckets["Fully funded"] += 1
    elif pct > 0:
        capex_buckets["Partially funded"] += 1
    else:
        capex_buckets["Unfunded"] += 1

# -- Distribution panel 3: Predictive Portfolio Health --
health_buckets = {"High (≥70)": 0, "Medium (40-69)": 0, "Low (<40)": 0, "Under monitoring": 0, "Not yet tracked": 0}
for r in active_rows:
    pred = predictions[r["project_id"]]
    if pred["status"] == "predicted":
        s = pred["success_score"]
        if s >= 70: health_buckets["High (≥70)"] += 1
        elif s >= 40: health_buckets["Medium (40-69)"] += 1
        else: health_buckets["Low (<40)"] += 1
    else:
        health_buckets["Under monitoring"] += 1
health_buckets["Not yet tracked"] = sum(1 for p in all_projects if p["status"] in ("draft", "pmo_review", "analysis"))

# -- Distribution panel 4: Portfolio Value by Business Unit --
bu_value = {}
for p in pipeline_projects:
    bu = p.get("business_unit") or "Unassigned"
    bu_value[bu] = bu_value.get(bu, 0) + (p["business_impact_usd"] or 0)
bu_value = dict(sorted(bu_value.items(), key=lambda kv: -kv[1]))

def bar_rows(buckets, fmt=lambda v: str(v)):
    mx = max(buckets.values()) or 1
    out = []
    for label, val in buckets.items():
        pct = round(100 * val / mx) if mx else 0
        out.append(f"""<div class="bar-row"><div class="bar-label">{esc(label)}</div>
<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
<div class="bar-val">{fmt(val)}</div></div>""")
    return "".join(out)

dist_status_html = bar_rows(status_buckets)
dist_capex_html = bar_rows(capex_buckets) if any(capex_buckets.values()) else '<div class="empty">No active project currently carries a CAPEX ask.</div>'
dist_health_html = bar_rows(health_buckets)
dist_bu_html = bar_rows(bu_value, fmt=lambda v: f"${v:,.0f}") if bu_value else '<div class="empty">No pipeline-stage projects.</div>'

# ---------------------------------------------------------------------------
# 3. Needs Attention (Projects tab) — real pending Gate 3 change request(s).
# ---------------------------------------------------------------------------
na_cards = []
for cr in needs_attention:
    proj = get_project_by_ref(conn, cr["original_project_id"]) or {}
    na_cards.append(f"""<div class="card red">
<div class="top"><div><div class="name">{esc(proj.get('project_name', cr['original_project_id']))}</div>
<div class="meta">{esc(cr['original_project_id'])} • requested by {esc(cr['requested_by'] or '—')}</div></div>
<span class="pill red">Needs PMO authorization</span></div>
<div class="meta" style="margin-top:6px">Agent 12: {esc(cr['reason'])}</div>
<div style="margin-top:10px;text-align:right">
<button class="btn-sm accept" onclick="gate3Decide({cr['id']}, '{esc(proj.get('project_name',''))}', 'Approved')">✓ Approve</button>
<button class="btn-sm hold" onclick="gate3Decide({cr['id']}, '{esc(proj.get('project_name',''))}', 'Cancelled')">⏸ Cancel change</button>
<button class="btn-sm reject" onclick="gate3Decide({cr['id']}, '{esc(proj.get('project_name',''))}', 'Rejected')">✕ Reject</button>
</div>
<div class="decision-result" id="result-gate3-{cr['id']}"></div>
</div>""")
needs_attention_html = "".join(na_cards) or '<div class="empty">Nothing needs PMO attention right now.</div>'

AGENT_LABELS = {
    "agent1_intake_parser": "AGENT 1 · INTAKE PARSER",
    "agent2_duplicate_checker": "AGENT 2 · DUPLICATE CHECKER",
    "agent3_duplicate_rejection_notifier": "AGENT 3 · DUPLICATE NOTIFIER",
    "agent4_pmo_router": "AGENT 4 · PMO ROUTER",
    "agent5_business_impact": "AGENT 5 · BUSINESS IMPACT",
    "agent6_knowledge_crosscheck": "AGENT 6 · KNOWLEDGE CROSS-CHECK",
    "agent7_acceptance_handler": "AGENT 7 · ACCEPTANCE HANDLER",
    "agent8_rejection_feedback_composer": "AGENT 8 · REJECTION FEEDBACK",
    "agent9_dashboard_service": "AGENT 9 · DASHBOARD SERVICE",
    "agent10_success_predictor": "AGENT 10 · SUCCESS PREDICTOR",
    "agent11_update_logger": "AGENT 11 · UPDATE LOGGER",
    "agent12_change_evaluator": "AGENT 12 · CHANGE EVALUATOR",
    "agent13_opl_composer": "AGENT 13 · OPL COMPOSER",
}

# ---------------------------------------------------------------------------
# 4. Queued projects (Projects tab, collapsible) — real Gate 2 queue.
# ---------------------------------------------------------------------------
queue_cards = []
for r in queue_rows:
    sid = r["submission_id"]
    pid = r["project_id"] or sid
    a5 = get_latest_agent_payload(conn, pid, "agent5_business_impact") or {}
    a6 = get_latest_agent_payload(conn, pid, "agent6_knowledge_crosscheck") or {}
    fast_track = (r["capex_usd"] or 0) < cfg.GATE2_FAST_TRACK_CAPEX_USD
    safe_id = sid.replace("-", "_")
    queue_cards.append(f"""<div class="card" id="card-{safe_id}">
<div class="top"><div><div class="name">{esc(r['project_name'])}</div>
<div class="meta">{esc(r['region'] or '—')} • {esc(r['business_unit'] or '—')}</div></div>
<div style="font-weight:700">${(r['capex_usd'] or 0):,.0f}</div></div>
<div>
<span class="pill">Agent 5: {esc(a5.get('margin_impact','—'))}</span>
<span class="pill">Agent 6: {esc(a6.get('verdict','—'))}</span>
{'<span class="pill green">✓ fast-track eligible</span>' if fast_track else ''}
</div>
<div style="margin-top:10px;text-align:right"><button class="btn" onclick="toggleReview('{safe_id}')">Review</button></div>
<div class="decision-panel" id="decision-{safe_id}">
<div class="meta" style="margin-bottom:8px">Agent 6 rationale: {esc(a6.get('citation', 'no citation on record'))}</div>
<button class="btn-sm accept" onclick="decide('{safe_id}', '{esc(r['project_name'])}', 'Accepted')">✓ Accept</button>
<button class="btn-sm hold" onclick="decide('{safe_id}', '{esc(r['project_name'])}', 'Held')">⏸ Hold</button>
<button class="btn-sm reject" onclick="decide('{safe_id}', '{esc(r['project_name'])}', 'Rejected')">✕ Reject</button>
<div class="decision-result" id="result-{safe_id}"></div>
</div>
</div>""")
queue_html = "".join(queue_cards) or '<div class="empty">Queue is empty.</div>'

# ---------------------------------------------------------------------------
# 5. Active projects (Projects tab, collapsible) — real accepted/in_progress rows, each with a
#    real-behavior "Flag for review" action.
# ---------------------------------------------------------------------------
active_table_rows = []
for r in active_rows:
    pred = predictions[r["project_id"]]
    score_txt = f"{pred['success_score']:.1f}" if pred["status"] == "predicted" else "monitoring"
    risk = r.get("risk_indicator") or "gray"
    is_flagship = r["project_id"] == FLAGSHIP_PROJECT_ID
    flag_btn = (f'<button class="btn-sm" onclick="showView(\'projects\');toast(\'Already flagged — see Needs Attention above.\')">Already flagged</button>'
                if is_flagship else
                f'<button class="btn-sm" onclick="flagForReview(\'{esc(r["project_id"])}\', \'{esc(r["project_name"])}\')">Flag for review</button>')
    active_table_rows.append(f"""<tr>
<td><div style="font-weight:700">{esc(r['project_name'])}</div>
<div class="meta" style="font-size:10.5px;color:var(--on-surface-variant)">{esc(r['project_id'])}</div></td>
<td><span class="pill {risk}">{esc(risk)}</span></td>
<td>{esc(score_txt)}</td>
<td>{flag_btn}</td>
</tr>""")
active_html = "".join(active_table_rows)

# ---------------------------------------------------------------------------
# 6. Mail — Inbox (to PMO) / Sent (to submitters) / Draft (real PMO/stakeholder comments) / Delete.
#    v4: no longer statically rendered. All four start empty and are populated live by JS as the
#    PMO clicks Execute in Live Workflow — see the postMessage listener + injectMail()/
#    injectDraftComments() near the bottom. AGENT_LABELS and CASE6_COMMENTS are the only data this
#    needs client-side (notification payloads themselves arrive live, already carrying
#    trigger_label/recipient/channel/subject/body straight from render_visualizer.py).
# ---------------------------------------------------------------------------
AGENT_LABELS_JSON = json.dumps(AGENT_LABELS)
CASE6_COMMENTS_JSON = json.dumps([
    {"author": c["author"], "role": c["role"], "body": c["body"],
     "is_flagged_concern": bool(c["is_flagged_concern"]), "linked_gate": c.get("linked_gate")}
    for c in case6_comments
])
FOLDERS = {"inbox": "Inbox", "sent": "Sent", "draft": "Draft", "delete": "Delete"}
folder_items = "".join(
    f'<div class="folder-item" onclick="showView(\'mail-{k}\')" id="nav-mail-{k}">'
    f'<span>{esc(label)}</span><span class="count" id="count-{k}">0</span></div>'
    for k, label in FOLDERS.items()
)
EMPTY_MAIL = {
    "inbox": "Nothing yet — click Execute on a case in Live Workflow to see a real message arrive.",
    "sent": "Nothing yet — click Execute on a case in Live Workflow to see a real message arrive.",
    "draft": "Nothing yet — Case 6 is the one with real PMO/stakeholder comments; execute it in Live Workflow.",
    "delete": "Nothing in Delete — notifications aren't deleted in this build.",
}

# ---------------------------------------------------------------------------
# 7. Live Workflow — case 1-6 switcher (Case 7, borderline duplicate, dropped from this switcher
#    per explicit request — its scenario still runs above for real portfolio data). The node/edge
#    graph below is built ONCE, straight from dashboard/render_visualizer.py's own NODE_POS/EDGES
#    (the real production layout) — same generation code that file uses for its edge <line>/<path>
#    elements and node <div>s, just emitted into THIS document instead of a separate file. All 6
#    intake cases share this one graph;
#    Execute loads that case's real sequence (from _build_sequence(), same real branch logic) and
#    animates it in place, calling injectNotification() directly — no iframe, no postMessage.
# ---------------------------------------------------------------------------
def _build_shared_graph():
    edge_svg = []
    for a, b in VIZ_EDGES:
        ax, ay, aw, ah = VIZ_NODE_POS[a][:4]
        bx, by, bw, bh = VIZ_NODE_POS[b][:4]
        eid = f"edge_{a}__{b}"
        dx, dy = abs(bx - ax), abs(by - ay)
        if dx < 20:
            if by < ay:
                x1, y1, x2, y2 = ax, ay - ah / 2, bx, by + bh / 2
            else:
                x1, y1, x2, y2 = ax, ay + ah / 2, bx, by - bh / 2
            edge_svg.append(f'<line id="{eid}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="edge" marker-end="url(#arrow)"/>')
        elif dy < 20:
            if bx > ax:
                x1, y1, x2, y2 = ax + aw / 2, ay, bx - bw / 2, by
            else:
                x1, y1, x2, y2 = ax - aw / 2, ay, bx + bw / 2, by
            edge_svg.append(f'<line id="{eid}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="edge" marker-end="url(#arrow)"/>')
        else:
            if bx > ax:
                sx, sy, ex, ey = ax + aw / 2, ay, bx - bw / 2, by
            else:
                sx, sy, ex, ey = ax - aw / 2, ay, bx + bw / 2, by
            mid_x = (sx + ex) / 2
            edge_svg.append(f'<path id="{eid}" d="M{sx:.1f},{sy:.1f} L{mid_x:.1f},{sy:.1f} L{mid_x:.1f},{ey:.1f} L{ex:.1f},{ey:.1f}" class="edge" fill="none" marker-end="url(#arrow)"/>')

    node_divs = []
    for nid, (cx, cy, w, h, shape, lbl) in VIZ_NODE_POS.items():
        inner = "<br>".join(lbl.split("\n"))
        node_divs.append(f'<div class="vnode {shape}" id="vnode-{nid}" '
                          f'style="left:{cx-w/2:.1f}px;top:{cy-h/2:.1f}px;width:{w}px;height:{h}px;"><span>{inner}</span></div>')

    canvas_w = max(p[0] + p[2] // 2 for p in VIZ_NODE_POS.values()) + 60
    canvas_h = max(p[1] + p[3] // 2 for p in VIZ_NODE_POS.values()) + 60
    return "\n".join(edge_svg), "\n".join(node_divs), canvas_w, canvas_h

GRAPH_EDGES_SVG, GRAPH_NODES_HTML, GRAPH_CANVAS_W, GRAPH_CANVAS_H = _build_shared_graph()

case_buttons, case_panes = [], []
CASE_SEQUENCES = {}
CASE_NOTIFS = {}
CASE_GATE2 = {}
ROLE_LABELS = {"pmo": "PMO", "regulatory": "REGULATORY", "stakeholder": "STAKEHOLDER"}
for key in SCENARIO_ORDER:
    if key == "7_borderline_duplicate_llm_adjudication":
        # Removed from the Live Workflow switcher per explicit request (still run above for real
        # portfolio data — Dashboard KPIs/Projects still reflect its accepted project — just not
        # shown as its own case here). Cases 8/9 (post-acceptance updates) shift down to 7/8 below
        # so the switcher reads Case 1-8 with no gap.
        continue
    c = per_case[key]
    active_cls = " active" if c["num"] == 1 else ""
    case_buttons.append(f'<button class="case-btn{active_cls}" id="case-btn-{c["num"]}" '
                         f'onclick="showCase({c["num"]})">Case {c["num"]}</button>')
    disp = "block" if c["num"] == 1 else "none"

    if key in GATE2_DECISION_KEYS:
        g = c["gate2"]
        CASE_GATE2[c["num"]] = {
            "prefix": c["sequence"], "prefix_notifs": c["notifications"],
            "reject_tail": g["reject_tail"], "reject_notifs": g["reject_notifications"], "reject_reason": g["reject_reason"],
            "accept_tail": g["accept_tail"], "accept_notifs": g["accept_notifications"],
        }
        comments_html = ""
        if g["comments"]:
            cards = []
            for cm in g["comments"]:
                flag_badge = ' <span style="color:#a32d2d">\U0001f6a9 flagged</span>' if cm["is_flagged_concern"] else ""
                gate_note = f' · {esc(cm["linked_gate"])}' if cm.get("linked_gate") else ""
                cards.append(f"""<div class="notif-card">
<div class="tag">{esc(ROLE_LABELS.get(cm['role'], cm['role'].upper()))} COMMENT — {esc(cm['author'])}{gate_note}</div>
<div class="body">{esc(cm['body'])}{flag_badge}</div></div>""")
            comments_html = f"""<div class="panel">
<h3>Stakeholder &amp; PMO comments</h3>
{"".join(cards)}
</div>"""
        case_panes.append(f"""<div class="case-pane" id="case-pane-{c['num']}" style="display:{disp}">
<div class="panel" style="margin-bottom:12px">
<div style="display:flex;justify-content:space-between;align-items:baseline">
<h3>Case {c['num']} — {esc(c['title'])}</h3>
<button class="btn" onclick="executeGate2Case({c['num']})">▶ Execute</button>
</div>
<div class="sub">{esc(c['outcome'])} — project: <b>{esc(c['project_name'])}</b></div>
<div class="sub" id="exec-status-{c['num']}">Not yet executed this session.</div>
</div>
{comments_html}
<div class="panel decision-panel" id="decision-case{c['num']}" style="display:none">
<h3>Gate 2 — PMO decision</h3>
<div class="meta" style="margin-bottom:8px">Reject reason on file (AI-composed): "{esc(g['reject_reason'])}"</div>
<button class="btn-sm accept" onclick="gate2CaseDecide({c['num']}, 'Proceed')">✓ Proceed</button>
<button class="btn-sm hold" onclick="gate2CaseDecide({c['num']}, 'Hold')">⏸ Hold</button>
<button class="btn-sm reject" onclick="gate2CaseDecide({c['num']}, 'Reject')">✕ Reject</button>
<div class="decision-result" id="result-case{c['num']}"></div>
</div>
</div>""")
        continue

    CASE_SEQUENCES[c["num"]] = c["sequence"]
    CASE_NOTIFS[c["num"]] = c["notifications"]
    case_panes.append(f"""<div class="case-pane" id="case-pane-{c['num']}" style="display:{disp}">
<div class="panel" style="margin-bottom:12px">
<div style="display:flex;justify-content:space-between;align-items:baseline">
<h3>Case {c['num']} — {esc(c['title'])}</h3>
<button class="btn" onclick="executeCase({c['num']})">▶ Execute</button>
</div>
<div class="sub">{esc(c['outcome'])} — actual result: <b>{esc(c['project_name'])}</b>, final status <b>{esc(c['final_status'])}</b></div>
<div class="sub" id="exec-status-{c['num']}">Not yet executed this session.</div>
</div>
</div>""")
case_buttons_html = "".join(case_buttons)
case_panes_html = "".join(case_panes)
CASE_SEQUENCES_JSON = json.dumps(CASE_SEQUENCES)
CASE_NOTIFS_JSON = json.dumps(CASE_NOTIFS)
CASE_GATE2_JSON = json.dumps(CASE_GATE2)

# Case 7 (favorable, real auto-apply) and Case 8 (unfavorable, real Gate 3 escalation — same real
# result already backing the Needs Attention panel on the Projects tab) — shifted down from 8/9 to
# 7/8 per explicit request, once Case 7 (borderline duplicate) was dropped from this switcher.
# Neither has a node/edge visualizer like cases 1-6 (render_visualizer.py is intake-flow-only,
# agents 1-10) — there's no invented graph standing in for one; instead each pane shows the actual
# submitted email (CHANGE_CASE_EMAILS, real, same text the production composer uses) and Agent 12's
# actual verdict. Both loop back to a PMO decision panel (Proceed/Hold/Reject) on Execute, styled
# like the Gate 2 review panel already used for the queue. Framed honestly where the real pipeline
# and this decision panel disagree: this Case 7's real behavior is zero-touch auto-apply (Agent 12
# has no code path to block a favorable/no-regression change), so Hold/Reject there are marked
# preview-only demo affordances, not something the real system does. This Case 8 is the real thing —
# its decision panel targets the SAME change_request_id already sitting in Projects → Needs
# Attention (Gate 3), not a second invented one.
fav = de.CHANGE_DEMO_PAYLOADS["favorable"]
unfav = de.CHANGE_DEMO_PAYLOADS["unfavorable"]
case8_change_request_id = update_result.get("change_request_id")
case_buttons_html += ('<button class="case-btn" id="case-btn-7" onclick="showCase(7)">Case 7</button>'
                      '<button class="case-btn" id="case-btn-8" onclick="showCase(8)">Case 8</button>'
                      '<button class="btn-sm" onclick="restartWorkflowDemo()" style="margin-left:10px">↻ Restart demo</button>')
case_panes_html += f"""
<div class="case-pane" id="case-pane-7" style="display:none">
  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <h3>Case 7 — Project update: favorable (auto-applies)</h3>
      <button class="btn" onclick="executeCase7()">▶ Execute</button>
    </div>
    <div class="sub">Real result: Agent 12 evaluated this as <b>{esc(case7_result['evaluation'])}</b> — "{esc(case7_result['reason'])}" — real behavior applies this with zero PMO touch time.</div>
    <div class="sub">Change: CAPEX ${fav['capex_usd']:,.0f} · launch pulled in to {esc(fav['expected_launch_date'])}. No regression on any governance axis.</div>
    <div class="sub" id="exec-status-7">Not yet executed this session.</div>
  </div>
  <div class="panel">
    <h3>Submitted email</h3>
    <div class="notif-card"><div class="tag">FROM {esc(CASE7_EMAIL['from'])}</div>
    <div class="subj">{esc(CASE7_EMAIL['subject'])}</div>
    <div class="body">{esc(CASE7_EMAIL['body'])}</div></div>
  </div>
  <div class="panel decision-panel" id="decision-case7" style="display:none">
    <h3>Gate 2 — PMO decision</h3>
    <div class="meta" style="margin-bottom:8px">Agent 12 recommends <b>Proceed</b> — favorable, no regression on any axis.</div>
    <button class="btn-sm accept" onclick="case7Decide('Proceed')">✓ Proceed</button>
    <button class="btn-sm hold" onclick="case7Decide('Hold')">⏸ Hold</button>
    <button class="btn-sm reject" onclick="case7Decide('Reject')">✕ Reject</button>
    <div class="decision-result" id="result-case7"></div>
  </div>
</div>
<div class="case-pane" id="case-pane-8" style="display:none">
  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <h3>Case 8 — Project update: needs PMO authorization</h3>
      <button class="btn" onclick="executeCase8()">▶ Execute</button>
    </div>
    <div class="sub">Real result: Agent 12 evaluated this as <b>{esc(update_result['evaluation'])}</b> — "{esc(update_result['reason'])}" — the live project row stays untouched until PMO decides.</div>
    <div class="sub">Change requested: CAPEX ${unfav['capex_usd']:,.0f} · risk elevated to {esc(unfav['risk_indicator'])}. Real change_request_id={esc(str(case8_change_request_id))} — the same one in Projects → Needs Attention.</div>
    <div class="sub" id="exec-status-8">Not yet executed this session.</div>
  </div>
  <div class="panel">
    <h3>Submitted email</h3>
    <div class="notif-card"><div class="tag">FROM {esc(CHANGE_CASE_EMAILS_UNFAVORABLE['from'])}</div>
    <div class="subj">{esc(CHANGE_CASE_EMAILS_UNFAVORABLE['subject'])}</div>
    <div class="body">{esc(CHANGE_CASE_EMAILS_UNFAVORABLE['body'])}</div></div>
  </div>
  <div class="panel decision-panel" id="decision-case8" style="display:none">
    <h3>Gate 2 — PMO decision</h3>
    <div class="meta" style="margin-bottom:8px">Agent 12 flagged: {esc(update_result['reason'])} — real Gate 3 authorization needed.</div>
    <button class="btn-sm accept" onclick="case8Decide('Proceed')">✓ Proceed</button>
    <button class="btn-sm hold" onclick="case8Decide('Hold')">⏸ Hold</button>
    <button class="btn-sm reject" onclick="case8Decide('Reject')">✕ Reject</button>
    <div class="decision-result" id="result-case8"></div>
  </div>
</div>"""
CASE7_NOTIF_JSON = json.dumps({
    "trigger_agent": case7_notif["trigger_agent"], "trigger_label": AGENT_LABELS.get(case7_notif["trigger_agent"], case7_notif["trigger_agent"]),
    "recipient": case7_notif["recipient"], "channel": case7_notif["channel"],
    "subject": case7_notif["subject"], "body": case7_notif["body"],
})

# ---------------------------------------------------------------------------
# 8. Agent Settings — all 13 agents + real config.py tunables.
# ---------------------------------------------------------------------------
def field(label, value, key, kind="number", step="any", hint=None):
    # "Recommended: X" is generated straight from the real config.py value itself (never a separate
    # invented number) — the field always shows what the shipped default is, even after an in-session
    # edit, and Reset restores exactly this value via each input's data-default attribute.
    if isinstance(value, dict):
        disp = ", ".join(f"{k}={v}" for k, v in value.items())
        rows = "".join(f'<div class="mini-field"><span>{esc(k)}</span>'
                        f'<input class="field-sm" type="number" step="any" value="{v}" data-default="{v}" '
                        f'data-key="{esc(key)}.{esc(k)}"/></div>' for k, v in value.items())
        hint_html = f'<div class="field-hint"><b>Recommended: {esc(disp)}</b>{(" — " + esc(hint)) if hint else ""}</div>'
        return f'<div class="setting-row"><label class="field-label">{esc(label)}</label>{rows}{hint_html}</div>'
    hint_html = f'<div class="field-hint"><b>Recommended: {esc(str(value))}</b>{(" — " + esc(hint)) if hint else ""}</div>'
    return (f'<div class="setting-row"><label class="field-label">{esc(label)}</label>'
            f'<input class="field" type="{kind}" step="{step}" value="{esc(str(value))}" data-default="{esc(str(value))}" data-key="{esc(key)}"/>{hint_html}</div>')

AGENTS = [
    ("1", "Intake Parser", "Deterministic parse + validation; Haiku fallback for free-text fields.", [
        field("Model", cfg.MODEL_ROUTING["agent1_intake_parser"], "agent1.model", "text",
              hint="reads new submissions; cheap model is fine, it's extraction not judgment"),
        field("SLA target (s)", cfg.SLA_TARGETS["agent1_parse"], "agent1.sla",
              hint="alarm threshold only, doesn't change behavior"),
    ]),
    ("2", "Duplicate Checker", "Embedding similarity + Sonnet adjudication for borderline matches.", [
        field("Auto-flag threshold", cfg.DUPLICATE_AUTO_FLAG_THRESHOLD, "agent2.auto_flag",
              hint="raise = only near-identical copies flagged; lower = more false positives"),
        field("Not-duplicate threshold", cfg.DUPLICATE_NOT_DUPLICATE_THRESHOLD, "agent2.not_dup",
              hint="below this, clearly unrelated; between here and auto-flag is 'ask an AI judge'"),
        field("Reuse similarity threshold", cfg.REUSE_SIMILARITY_THRESHOLD, "agent2.reuse",
              hint="looser bar — surfaces 'similar past project,' not a duplicate flag"),
        field("Borderline adjudication model", cfg.MODEL_ROUTING["agent2_borderline_adjudication"], "agent2.model", "text",
              hint="judges unclear matches; stronger model = fewer wrong calls, higher cost"),
        field("SLA target (s)", cfg.SLA_TARGETS["agent2_duplicate_check"], "agent2.sla",
              hint="time budget for the whole duplicate check"),
    ]),
    ("3", "Duplicate Rejection Notifier", "Deterministic — no LLM call, no tunables.", []),
    ("4", "PMO Router", "Deterministic routing + Gate 2 batch cadence.", [
        field("Gate 2 batch interval (days)", cfg.GATE2_BATCH_INTERVAL_DAYS, "agent4.batch_days",
              hint="shorter = more frequent, smaller reviews; longer = fewer, bigger sittings"),
        field("Fast-track CAPEX ceiling (USD)", cfg.GATE2_FAST_TRACK_CAPEX_USD, "agent4.fast_track",
              hint="projects under this skip the queue; raise to fast-track bigger asks"),
    ]),
    ("5", "Business Impact Analyzer", "Sonnet reasoning over playbook margin + regional CAPEX budgets.", [
        field("Model", cfg.MODEL_ROUTING["agent5_business_impact"], "agent5.model", "text",
              hint="judges the financial case; a judgment call, so a stronger model"),
        field("Margin window (months)", cfg.MARGIN_WINDOW_MONTHS, "agent5.margin_window",
              hint="shorter = stricter financial bar; longer = more patience for slow-burn projects"),
        field("Budget headroom lens threshold", cfg.BUDGET_HEADROOM_LENS_THRESHOLD, "agent5.headroom",
              hint="below this % budget left, system nudges PMO toward cheaper/safer picks"),
        field("Regional CAPEX budgets (USD)", cfg.REGIONAL_CAPEX_BUDGET_USD, "agent5.regional_capex",
              hint="yearly spend cap per region; raise a region's number for more headroom"),
        field("SLA target, combined w/ Agent 6 (s)", cfg.SLA_TARGETS["agent5_6_combined"], "agent5.sla",
              hint="time budget for business-impact + knowledge-check together"),
    ]),
    ("6", "Knowledge Cross-Checker", "Sonnet, CAG over full playbook/PVP text; citation required or verdict forces inconclusive.", [
        field("Model", cfg.MODEL_ROUTING["agent6_knowledge_crosscheck"], "agent6.model", "text",
              hint="checks strategic fit; no citation = forced 'inconclusive' regardless of model"),
        field("Playbook/PVP staleness (days)", cfg.PLAYBOOK_PVP_STALENESS_DAYS, "agent6.staleness",
              hint="lower = get warned sooner that policy docs need a review"),
        field("Regulatory staleness window", cfg.POLITICAL_REGULATORY_STALENESS, "agent6.reg_staleness", "text",
              hint="regulation moves faster than playbook/PVP, so it's checked separately"),
    ]),
    ("7", "Acceptance Handler", "Deterministic — only writer of status=accepted + project_id.", []),
    ("7.1", "Monthly Briefing", "Sonnet summarization of the period's portfolio activity.", [
        field("Model", cfg.MODEL_ROUTING["agent7_1_monthly_briefing"], "agent71.model", "text",
              hint="writes the monthly summary only — no effect on any project decision"),
    ]),
    ("8", "Rejection Feedback Composer", "Haiku composition + Haiku tone check before send.", [
        field("Composer model", cfg.MODEL_ROUTING["agent8_rejection_feedback"], "agent8.model", "text",
              hint="writes the rejection email a submitter receives"),
        field("Tone-check model", cfg.MODEL_ROUTING["agent8_tone_check"], "agent8.tone_model", "text",
              hint="second pass checking the email isn't harsh before it sends"),
    ]),
    ("9", "Dashboard Service", "Deterministic — read-only queries backing every view in this preview.", []),
    ("10", "Success Predictor", "Deterministic weighted formula — no LLM call.", [
        field("Score weights", cfg.SUCCESS_SCORE_WEIGHTS, "agent10.weights",
              hint="how much each factor counts toward the 0-100 score; should sum to 1.0"),
        field("Risk penalty by color", cfg.RISK_PENALTY_BY_COLOR, "agent10.risk_penalty",
              hint="points a yellow/red status subtracts (0=none, 1=full penalty)"),
        field("Min age before scoring (days)", cfg.SUCCESS_PREDICTOR_MIN_AGE_DAYS, "agent10.min_age",
              hint="raise = newer projects stay 'under monitoring' longer before scoring"),
    ]),
    ("11", "Update Logger", "Deterministic parse + capture of a submitted status update.", []),
    ("12", "Change Evaluator", "Deterministic favorable/unfavorable check across risk, schedule, CAPEX, resource axes — no LLM call.", []),
    ("13", "OPL Composer", "Deterministic — publishes a completed project's one-pager into the knowledge base.", []),
]
agent_cards_html = "".join(f"""<div class="panel">
<div style="display:flex;justify-content:space-between;align-items:baseline">
<h3>AGENT {esc(num)} · {esc(name).upper()}</h3>
<div><button class="btn-sm" onclick="resetAgentSettings(this)">↺ Reset to recommended</button><button class="btn-sm" onclick="saveAgentSettings(this)">Save</button></div>
</div>
<div class="sub">{esc(desc)}</div>
{"".join(fields) if fields else '<div class="empty" style="padding:8px 0;text-align:left">No tunable parameters.</div>'}
</div>""" for num, name, desc, fields in AGENTS)

system_wide_html = f"""<div class="panel">
<div style="display:flex;justify-content:space-between;align-items:baseline">
<h3>SYSTEM-WIDE CONTROLS</h3>
<div><button class="btn-sm" onclick="resetAgentSettings(this)">↺ Reset to recommended</button><button class="btn-sm" onclick="saveAgentSettings(this)">Save</button></div>
</div>
<div class="sub">Not tied to one agent — bounded-iteration + cost controls (§8.1) applied across every reasoning agent.</div>
{field("Max reasoning turns", cfg.MAX_REASONING_TURNS, "sys.max_turns",
       hint="attempts before an AI gives up and escalates to a human; higher = tries harder, costs more")}
{field("Max retries", cfg.MAX_RETRIES, "sys.max_retries",
       hint="retries on a failed AI call before giving up; higher = more resilient, slower to fail")}
{field("Per-agent timeout (s)", cfg.PER_AGENT_TIMEOUT_SECONDS, "sys.timeout",
       hint="how long one agent step runs before it's treated as stuck")}
{field("End-to-end Gate 1 SLA (s)", cfg.SLA_TARGETS["end_to_end_gate1"], "sys.e2e_sla",
       hint="target time from submission to PMO notified; a measured target, not a hard cutoff")}
</div>"""

# ---------------------------------------------------------------------------
# 9. Documents tab — real files + TECH-SPEC governance excerpt.
# ---------------------------------------------------------------------------
def read_doc(relpath):
    p = os.path.join(REPO_ROOT, relpath)
    with open(p, "r") as f:
        return f.read()

pvp_text = read_doc("data/pvp.md")
playbook_text = read_doc("data/playbook.md")
regulatory_text = read_doc("data/regulatory.md")
tech_spec = read_doc("TECH-SPEC.md")
gstart = tech_spec.find("## 8.2 Guardrails")
gend = tech_spec.find("## 8.3 Performance SLAs")
governance_text = tech_spec[gstart:gend].strip() if gstart != -1 and gend != -1 else "(Governance section not found in TECH-SPEC.md)"

DOCS = [
    ("pvp", "PVP — Core Values, Ethics, Working Principles", "data/pvp.md", pvp_text),
    ("playbook", "Playbook — Strategic & Investment Policy", "data/playbook.md", playbook_text),
    ("regulatory", "Regulatory Updates", "data/regulatory.md", regulatory_text),
    ("governance", "Governance — System Guardrails (from TECH-SPEC.md §8.2, no standalone doc exists yet)", None, governance_text),
]
doc_tabs = "".join(f'<button class="case-btn{" active" if i==0 else ""}" id="doc-tab-{k}" '
                    f'onclick="showDoc(\'{k}\')">{esc(label.split(" —")[0])}</button>'
                    for i, (k, label, path, text) in enumerate(DOCS))
doc_tabs += '<button class="case-btn" id="doc-add-btn" onclick="addDocument()" title="Add a document">+ New document</button>'
doc_panes = "".join(f"""<div class="case-pane" id="doc-pane-{k}" style="display:{'block' if i==0 else 'none'}">
<div class="panel">
<h3>{esc(label)}</h3>
<div class="sub">{'Source: ' + esc(path) if path else 'No standalone governance document exists in this repo yet — shown from TECH-SPEC.md so the tab is real, not empty.'}</div>
<textarea class="field doc-editor" rows="18" data-doc="{k}">{esc(text)}</textarea>
<div style="margin-top:10px;text-align:right"><button class="btn-ghost" onclick="saveDoc('{k}')">Save</button></div>
</div>
</div>""" for i, (k, label, path, text) in enumerate(DOCS))
DOC_KEYS_INITIAL = [k for k, _, _, _ in DOCS]

# ---------------------------------------------------------------------------
# 10. Compose panel (moved into Projects tab — project actions live with project data).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 11. CSS
# ---------------------------------------------------------------------------
CSS = """
:root{
  --surface:#f7f9fb; --surface-container-lowest:#ffffff; --surface-container-low:#f2f4f6;
  --surface-container:#eceef0; --on-surface:#191c1e; --on-surface-variant:#44474c;
  --outline-variant:#c4c6cd; --primary:#041627; --on-primary:#ffffff; --secondary:#0040e0;
  --on-secondary-container:#efefff; --secondary-container:#dde1ff; --error:#ba1a1a;
  --success-surface:#E8F5E9; --success-text:#2e7d32; --warning-surface:#FFF9C4; --warning-text:#8a6d00;
  --danger-surface:#FFEBEE; --danger-text:#c62828; --border-subtle:#E2E8F0;
}
*{box-sizing:border-box}
body{margin:0;font-family:'JetBrains Mono',ui-monospace,monospace;background:var(--surface);color:var(--on-surface);
     display:flex;height:100vh;overflow:hidden;font-size:13px}
a{text-decoration:none;color:inherit}
#sidebar{width:230px;flex-shrink:0;background:var(--surface-container-lowest);border-right:1px solid var(--border-subtle);
         display:flex;flex-direction:column;transition:width .18s ease;overflow:hidden}
#sidebar.collapsed{width:64px}
#sb-head{display:flex;align-items:center;gap:10px;padding:18px 16px;border-bottom:1px solid var(--border-subtle)}
#sb-head .logo{width:32px;height:32px;border-radius:6px;background:var(--primary);color:#fff;display:flex;
                align-items:center;justify-content:center;flex-shrink:0;font-weight:700}
#sb-head .txt{white-space:nowrap;overflow:hidden}
#sb-head .txt b{display:block;font-size:13px}
#sb-head .txt span{display:block;font-size:11px;color:var(--on-surface-variant)}
.collapsed #sb-head .txt{display:none}
#collapse-btn{margin-left:auto;background:none;border:none;cursor:pointer;color:var(--on-surface-variant);
              padding:4px;border-radius:4px;flex-shrink:0}
#collapse-btn:hover{background:var(--surface-container)}
.collapsed #collapse-btn{margin-left:0}
.nav-section{padding:12px 10px}
.nav-label{font-size:10px;letter-spacing:.08em;color:var(--on-surface-variant);padding:4px 10px;white-space:nowrap}
.collapsed .nav-label{display:none}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:6px;color:var(--on-surface-variant);
          font-size:12.5px;white-space:nowrap;cursor:pointer;margin-bottom:2px}
.nav-item:hover{background:var(--surface-container-low)}
.nav-item.active{background:var(--secondary);color:#fff}
.nav-item .ic{width:16px;text-align:center;flex-shrink:0}
.collapsed .nav-item span.lbl{display:none}
.collapsed .nav-item{justify-content:center}
.nav-item .count{margin-left:auto;font-size:10px;background:var(--surface-container);color:var(--on-surface-variant);
                  padding:1px 6px;border-radius:8px}
.nav-item.active .count{background:rgba(255,255,255,.25);color:#fff}
.collapsed .nav-item .count{display:none}
#sb-foot{margin-top:auto;border-top:1px solid var(--border-subtle);padding:10px}
.folder-item{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;cursor:pointer;
             font-size:12px;color:var(--on-surface-variant)}
.folder-item:hover{background:var(--surface-container-low)}
.folder-item.active{background:var(--surface-container);color:var(--on-surface);font-weight:600}
.folder-item .count{margin-left:auto;font-size:10px;background:var(--surface-container);padding:1px 6px;
                     border-radius:8px}
.collapsed .folder-item span:not(.count){display:none}
#topbar{height:52px;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;
        padding:0 24px;gap:22px;background:var(--surface-container-lowest);flex-shrink:0}
.tab{font-size:13px;color:var(--on-surface-variant);padding:6px 0;cursor:pointer}
.tab.active{color:var(--on-surface);border-bottom:2px solid var(--secondary);font-weight:600}
#topbar .right{margin-left:auto;display:flex;align-items:center;gap:16px;color:var(--on-surface-variant)}
#topbar .right span{cursor:pointer;position:relative}
#topbar .right span:hover{color:var(--on-surface)}
.badge-dot{position:absolute;top:-3px;right:-5px;width:7px;height:7px;border-radius:50%;background:var(--secondary)}
#app{flex:1;display:flex;flex-direction:column;min-width:0}
#content{flex:1;overflow-y:auto;padding:20px}
.view{display:none}
.view.active{display:block}
#kpi-row{display:flex;gap:16px;margin-bottom:20px}
.kpi-card{flex:1;background:var(--surface-container-lowest);border:1px solid var(--border-subtle);
          border-radius:6px;padding:16px 18px}
.kpi-card .label{font-size:10.5px;letter-spacing:.06em;color:var(--on-surface-variant);margin-bottom:8px}
.kpi-card .value{font-size:26px;font-weight:700;font-family:'JetBrains Mono',monospace}
.kpi-card .foot{font-size:11px;color:var(--on-surface-variant);margin-top:4px}
.dist-row{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.dist-card{flex:1;min-width:320px;background:var(--surface-container-lowest);border:1px solid var(--border-subtle);
           border-radius:6px;padding:16px 18px}
.dist-card h4{margin:0 0 10px;font-size:12px;letter-spacing:.03em}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:11px}
.bar-label{width:150px;flex-shrink:0;color:var(--on-surface-variant)}
.bar-track{flex:1;height:8px;background:var(--surface-container);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;background:var(--secondary);border-radius:4px}
.bar-val{width:60px;text-align:right;font-weight:700;flex-shrink:0}
.panel{background:var(--surface-container-lowest);border:1px solid var(--border-subtle);border-radius:6px;
       padding:16px;margin-bottom:16px}
.panel h3{margin:0 0 4px;font-size:13px}
.panel .sub{font-size:11px;color:var(--on-surface-variant);margin-bottom:12px}
.card{background:#fff;border:1px solid var(--border-subtle);border-left:4px solid var(--outline-variant);
      border-radius:4px;padding:12px 14px;margin-bottom:10px}
.card.green{border-left-color:var(--success-text)}
.card.yellow{border-left-color:var(--warning-text)}
.card.red{border-left-color:var(--danger-text)}
.card .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.card .name{font-weight:700;font-size:13px}
.card .meta{font-size:11px;color:var(--on-surface-variant);margin-top:2px}
.pill{display:inline-block;font-size:10px;padding:2px 8px;border-radius:999px;background:var(--surface-container);
      color:var(--on-surface-variant);margin-right:6px;margin-top:6px}
.pill.green{background:var(--success-surface);color:var(--success-text)}
.pill.yellow{background:var(--warning-surface);color:var(--warning-text)}
.pill.red{background:var(--danger-surface);color:var(--danger-text)}
.btn{background:var(--primary);color:#fff;border:none;border-radius:4px;padding:6px 14px;font-size:11px;
     font-family:inherit;cursor:pointer}
.btn:hover{opacity:.85}
.btn-ghost{background:none;border:1px solid var(--secondary);color:var(--secondary);border-radius:4px;
           padding:6px 14px;font-size:11px;font-family:inherit;cursor:pointer}
.btn-ghost:hover{background:var(--on-secondary-container)}
.btn-sm{border:1px solid var(--border-subtle);background:#fff;border-radius:4px;padding:5px 10px;
        font-size:10.5px;font-family:inherit;cursor:pointer;margin-right:6px}
.btn-sm.accept{border-color:var(--success-text);color:var(--success-text)}
.btn-sm.accept:hover{background:var(--success-surface)}
.btn-sm.reject{border-color:var(--danger-text);color:var(--danger-text)}
.btn-sm.reject:hover{background:var(--danger-surface)}
.btn-sm.hold{border-color:var(--warning-text);color:var(--warning-text)}
.btn-sm.hold:hover{background:var(--warning-surface)}
.decision-panel{display:none;margin-top:10px;padding-top:10px;border-top:1px dashed var(--border-subtle)}
.decision-result{font-size:11px;font-weight:700;margin-top:8px;display:none}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;font-weight:600;color:var(--on-surface-variant);font-size:10.5px;padding:6px 4px;
   border-bottom:1px solid var(--border-subtle)}
td{padding:8px 4px;border-bottom:1px solid var(--surface-container)}
.notif-card{border:1px solid var(--secondary-container);background:var(--on-secondary-container);
            border-radius:6px;padding:12px 14px;margin-bottom:10px}
.notif-card .tag{font-size:10px;color:var(--secondary);font-weight:700;letter-spacing:.04em}
.notif-card .subj{font-weight:700;font-size:12.5px;margin:4px 0}
.notif-card .body{font-size:11.5px;color:var(--on-surface-variant);line-height:1.4;white-space:pre-line}
.notif-card .to{font-size:10px;color:var(--on-surface-variant);margin-top:6px}
.viz-wrap{border:1px solid var(--border-subtle);border-radius:6px;overflow:hidden;background:#fff;height:460px}
.viz-wrap.big{height:calc(100vh - 260px)}
.viz-wrap iframe{width:100%;height:100%;border:none}
/* ── Inline execution graph (ported from dashboard/render_visualizer.py's own node/edge model) ── */
line.edge,path.edge{stroke:#ccc;stroke-width:2;transition:stroke .25s,stroke-width .25s;fill:none}
line.edge.lit,path.edge.lit{stroke:var(--secondary);stroke-width:3}
line.edge.lit.done,path.edge.lit.done{stroke:var(--success-text)}
.vnode{position:absolute;display:flex;align-items:center;justify-content:center;text-align:center;
  font-size:11px;line-height:1.35;border-radius:10px;background:#fff;border:2px solid var(--outline-variant);
  color:#aaa;transition:background .3s,border-color .3s,color .3s,box-shadow .3s;box-sizing:border-box;
  padding:6px 8px;box-shadow:0 1px 4px rgba(0,0,0,.06);font-family:'JetBrains Mono',monospace}
.vnode.diamond{border-radius:0;transform:rotate(45deg);background:#fff5e0;border-color:#e8c96a}
.vnode.diamond span{transform:rotate(-45deg);font-weight:700;font-size:11px}
.vnode.chip{border-radius:20px;font-size:10px;font-style:italic;background:var(--surface-container);border-color:var(--border-subtle)}
.vnode.active{background:var(--on-secondary-container);border-color:var(--secondary);color:var(--on-surface);
  box-shadow:0 0 0 4px rgba(0,64,224,.18),0 2px 8px rgba(0,64,224,.12)}
.vnode.diamond.active{background:var(--on-secondary-container);border-color:var(--secondary)}
.vnode.complete{background:var(--success-surface);border-color:var(--success-text);color:var(--on-surface)}
.vnode.diamond.complete{background:var(--success-surface);border-color:var(--success-text)}
label.field-label{display:block;font-size:10px;letter-spacing:.06em;color:var(--on-surface-variant);
                   margin:10px 0 4px}
input.field, textarea.field{width:100%;border:1px solid var(--border-subtle);border-radius:4px;
    padding:8px;font-family:inherit;font-size:12px;background:var(--surface-container-low)}
input.field:focus, textarea.field:focus{outline:none;border-color:var(--secondary);background:#fff}
.doc-editor{font-family:'JetBrains Mono',monospace;font-size:11.5px;line-height:1.5}
.setting-row{margin-bottom:14px}
.field-hint{font-size:10.5px;color:var(--on-surface-variant);margin-top:3px;line-height:1.4;max-width:520px}
.field-hint b{color:var(--on-surface)}
.panel h3 + div .btn-sm{margin-left:6px;margin-right:0}
.mini-field{display:inline-flex;align-items:center;gap:6px;margin:4px 10px 4px 0;font-size:11px}
.field-sm{width:90px;border:1px solid var(--border-subtle);border-radius:4px;padding:4px 6px;font-family:inherit;font-size:11px}
.empty{color:var(--on-surface-variant);font-size:12px;text-align:center;padding:24px}
details.collapse-section{margin-bottom:16px}
details.collapse-section summary{cursor:pointer;font-size:13px;font-weight:700;padding:10px 0;list-style:none;
    display:flex;align-items:center;gap:8px}
details.collapse-section summary::-webkit-details-marker{display:none}
details.collapse-section summary .chev{transition:transform .15s}
details.collapse-section[open] summary .chev{transform:rotate(90deg)}
.case-btn{border:1px solid var(--border-subtle);background:#fff;border-radius:4px;padding:6px 12px;
          font-size:11px;font-family:inherit;cursor:pointer;margin-right:6px;margin-bottom:10px}
.case-btn.active{background:var(--primary);color:#fff;border-color:var(--primary)}
#toast{position:fixed;bottom:24px;right:24px;background:var(--primary);color:#fff;padding:12px 18px;
       border-radius:6px;font-size:12px;box-shadow:0 4px 20px rgba(0,0,0,.18);opacity:0;
       transform:translateY(8px);transition:opacity .18s,transform .18s;pointer-events:none;max-width:340px;z-index:999}
#toast.show{opacity:1;transform:translateY(0)}
.two-col{display:flex;gap:20px}
.two-col > div{flex:1;min-width:0}
.notif-card.new{animation:slideIn .25s ease}
@keyframes slideIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.count.bump{animation:bump .5s ease}
@keyframes bump{0%{transform:scale(1)}40%{transform:scale(1.4);background:var(--secondary);color:#fff}100%{transform:scale(1)}}
"""

# ---------------------------------------------------------------------------
# 12. Assemble
# ---------------------------------------------------------------------------
html_out = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>PMO Agent — Executive Precision (UI Preview)</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>{CSS}</style></head>
<body>
<div id="sidebar">
  <div id="sb-head">
    <div class="logo">◈</div>
    <div class="txt"><b>PMO Agent</b><span>Autonomous Co-pilot</span></div>
    <button id="collapse-btn" onclick="toggleSidebar()" title="Collapse">⟨⟨</button>
  </div>
  <div class="nav-section">
    <div class="nav-item active" id="nav-dashboard" onclick="showView('dashboard')"><span class="ic">▦</span><span class="lbl">Dashboard</span></div>
    <div class="nav-item" id="nav-projects" onclick="showView('projects')"><span class="ic">▢</span><span class="lbl">Projects</span><span class="count">{len(needs_attention)+len(active_rows)+len(queue_rows)}</span></div>
    <div class="nav-item" id="nav-agents" onclick="showView('agents')"><span class="ic">◍</span><span class="lbl">Agent Settings</span></div>
    <div class="nav-item" id="nav-documents" onclick="showView('documents')"><span class="ic">☷</span><span class="lbl">Documents</span></div>
  </div>
  <div class="nav-section">
    <div class="nav-label">MAIL — real notification log</div>
    {folder_items}
  </div>
  <div id="sb-foot">
    <div class="nav-item" id="nav-support" onclick="showView('support')"><span class="ic">?</span><span class="lbl">Support</span></div>
    <div class="nav-item" id="nav-logout" onclick="toast('Preview only — log out isn\\'t wired in this static build.')"><span class="ic">⏻</span><span class="lbl">Log out</span></div>
  </div>
</div>
<div id="app">
  <div id="topbar">
    <div class="tab active" id="tab-dashboard" onclick="showView('dashboard')">Dashboard</div>
    <div class="tab" id="tab-workflow" onclick="showView('workflow')">Live Workflow</div>
    <div class="right">
      <span onclick="showView('mail-inbox')" title="Notifications">\U0001f514<span class="badge-dot"></span></span>
      <span onclick="showView('workflow')" title="Recent activity">\U0001f550</span>
    </div>
  </div>
  <div id="content">

    <div class="view active" id="view-dashboard">
      <div id="kpi-row">
        <div class="kpi-card"><div class="label">TOTAL PROJECTS</div>
          <div class="value">{total_projects}</div>
          <div class="foot">every status, whole portfolio</div></div>
        <div class="kpi-card"><div class="label">PORTFOLIO VALUE</div>
          <div class="value">${portfolio_value:,.0f}</div>
          <div class="foot">business impact, analysis → accepted stage</div></div>
        <div class="kpi-card"><div class="label">APPROVED RATE</div>
          <div class="value">{approved_rate}%</div>
          <div class="foot">{approved} of {decided} decided proposals</div></div>
        <div class="kpi-card"><div class="label">AVG SUCCESS LIKELIHOOD</div>
          <div class="value">{f"{avg_success}%" if avg_success is not None else "—"}</div>
          <div class="foot">{len(scored)} of {len(active_rows)} old enough to score</div></div>
      </div>
      <div class="dist-row">
        <div class="dist-card"><h4>STATUS DISTRIBUTION</h4>{dist_status_html}</div>
        <div class="dist-card"><h4>CAPEX FUNDING COVERAGE</h4>{dist_capex_html}</div>
        <div class="dist-card"><h4>PREDICTIVE PORTFOLIO HEALTH</h4>{dist_health_html}</div>
        <div class="dist-card"><h4>PORTFOLIO VALUE BY BUSINESS UNIT</h4>{dist_bu_html}</div>
      </div>
      <div class="panel">
        <h3>Live Execution Visualizer</h3>
        <div class="sub">Every case's real audit-log-backed replay now lives in one place, driven by a real Execute button — see Live Workflow. (Not auto-played here anymore: nothing in this build executes without you clicking Execute.)</div>
        <div style="text-align:right"><button class="btn" onclick="showView('workflow')">Go to Live Workflow →</button></div>
      </div>
    </div>

    <div class="view" id="view-projects">
      <details class="collapse-section" open>
        <summary><span class="chev">▸</span>Needs Attention ({len(needs_attention)})</summary>
        <div class="sub" style="margin:-6px 0 12px">Real pending Gate 3 change requests — a post-acceptance update that regressed on at least one governance axis, so Agent 12 escalated instead of auto-applying it.</div>
        {needs_attention_html}
      </details>
      <details class="collapse-section">
        <summary><span class="chev">▸</span>Active Projects ({len(active_rows)})</summary>
        <div class="sub" style="margin:-6px 0 12px">Live accepted/in_progress status. "Flag for review" runs the same real Agent 11→Agent 12 update flow shown above.</div>
        <table><thead><tr><th>Project</th><th>Risk</th><th>Score</th><th></th></tr></thead>
        <tbody>{active_html}</tbody></table>
      </details>
      <details class="collapse-section">
        <summary><span class="chev">▸</span>Queued Projects — Gate 2 ({len(queue_rows)})</summary>
        <div class="sub" style="margin:-6px 0 12px">status='analysis' — Agent 6 finished, waiting on PMO's weekly batch decision.</div>
        {queue_html}
      </details>
    </div>

    <div class="view" id="view-agents">
      <div class="panel" style="background:var(--on-secondary-container);border-color:var(--secondary-container)">
        <div class="sub" style="margin-bottom:0">Real current values from <code>src/shared/config.py</code>. Edits apply to this preview session only (browser state) — not written back to the file.</div>
      </div>
      {agent_cards_html}
      {system_wide_html}
    </div>

    <div class="view" id="view-documents">
      <div>{doc_tabs}</div>
      {doc_panes}
    </div>

    <div class="view" id="view-workflow">
      <div class="panel">
        <h3>Live Workflow — Case 1–8</h3>
        <div class="sub">Cases 1-6: intake scenarios (Cases 3, 4, and 6 pause for a real Gate 2 PMO decision). Cases 7-8: real post-acceptance project updates — the same "Send a project update" action, split into its two real outcomes (favorable auto-apply vs. needs-authorization), each looping back to a PMO Proceed/Hold/Reject decision. The real app also has a Case 10 (complete a project → Agent 13 publishes an OPL) — not wired into this preview build yet. Every button replays that case's real, audit-log-backed execution.</div>
        <div>{case_buttons_html}</div>
      </div>
      {case_panes_html}
      <div class="panel">
        <h3>Workflow</h3>
        <div class="sub" id="graph-caption">Click Execute above to run this case's real, audit-log-backed pipeline — the same node/edge layout as dashboard/render_visualizer.py, rendered directly on this page.</div>
        <div id="graph-scroll" style="overflow:auto;max-width:100%;border:1px solid var(--border-subtle);border-radius:6px;background:#fff">
          <div id="graph-wrap" style="position:relative;width:{GRAPH_CANVAS_W}px;height:{GRAPH_CANVAS_H}px">
            <svg id="graph-edges" viewBox="0 0 {GRAPH_CANVAS_W} {GRAPH_CANVAS_H}" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible">
              <defs>
                <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#bbb"/></marker>
              </defs>
              {GRAPH_EDGES_SVG}
            </svg>
            {GRAPH_NODES_HTML}
          </div>
        </div>
        <div id="graph-log" style="margin-top:12px;font-size:11px;color:var(--on-surface-variant)"></div>
      </div>
    </div>

    <div class="view" id="view-mail-inbox">
      <div class="panel"><h3>Mail — Inbox</h3>
      <div class="sub">Real notifications addressed to PMO Team — arrives live as you Execute cases in Live Workflow.</div>
      <div id="mail-list-inbox"><div class="empty">{esc(EMPTY_MAIL['inbox'])}</div></div></div>
    </div>
    <div class="view" id="view-mail-sent">
      <div class="panel"><h3>Mail — Sent</h3>
      <div class="sub">Real notifications the agents sent to submitters/stakeholders on PMO's behalf — arrives live as you Execute cases.</div>
      <div id="mail-list-sent"><div class="empty">{esc(EMPTY_MAIL['sent'])}</div></div></div>
    </div>
    <div class="view" id="view-mail-draft">
      <div class="panel"><h3>Mail — Draft</h3>
      <div class="sub">Real PMO/stakeholder-authored comments (not agent-generated) — Case 6's Gate 2 review commentary, arrives once Case 6 reaches its Gate 2 decision point.</div>
      <div id="mail-list-draft"><div class="empty">{esc(EMPTY_MAIL['draft'])}</div></div></div>
    </div>
    <div class="view" id="view-mail-delete">
      <div class="panel"><h3>Mail — Delete</h3><div class="empty">{esc(EMPTY_MAIL['delete'])}</div></div>
    </div>

    <div class="view" id="view-support">
      <div class="panel">
        <h3>Support</h3>
        <div class="sub">Need help with this preview or the underlying pipeline? Reach out directly.</div>
        <div class="card"><div class="name">Calvin</div>
        <div class="meta"><a href="mailto:calvin@agentai.com.sg">calvin@agentai.com.sg</a></div></div>
        <div class="card"><div class="name">Miller</div>
        <div class="meta"><a href="mailto:miller@agentai.com.sg">miller@agentai.com.sg</a></div></div>
      </div>
    </div>

  </div>
</div>
<div id="toast"></div>
<script>
var AGENT_LABELS = {AGENT_LABELS_JSON};
var CASE6_COMMENTS = {CASE6_COMMENTS_JSON};
var CASE7_NOTIF = {CASE7_NOTIF_JSON};
var docCounter = 0;
function toggleSidebar(){{
  var sb = document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  document.getElementById('collapse-btn').innerText = sb.classList.contains('collapsed') ? '⟩⟩' : '⟨⟨';
}}
var toastTimer = null;
function toast(msg){{
  var t = document.getElementById('toast');
  t.innerText = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){{ t.classList.remove('show'); }}, 3400);
}}

var NAV_KEYS = ['dashboard','projects','agents','documents','support'];
var MAIL_KEYS = ['inbox','sent','draft','delete'];
function showView(key){{
  document.querySelectorAll('.view').forEach(function(v){{ v.classList.remove('active'); }});
  var el = document.getElementById('view-' + key);
  if(el) el.classList.add('active');
  NAV_KEYS.forEach(function(k){{ document.getElementById('nav-'+k).classList.toggle('active', k===key); }});
  MAIL_KEYS.forEach(function(k){{
    document.getElementById('nav-mail-'+k).classList.toggle('active', key === 'mail-'+k);
  }});
  document.getElementById('tab-dashboard').classList.toggle('active', key==='dashboard');
  document.getElementById('tab-workflow').classList.toggle('active', key==='workflow');
  document.getElementById('content').scrollTop = 0;
}}

// ---- Live Workflow: real Execute, rendered on THIS page (no iframe, no postMessage — that path
// turned out to be the actual bug: some browsers silently refuse to paint a file:// iframe nested
// inside a file:// parent page, so "Running…" would show but the graph never appeared, and no
// postMessage ever fired either, which is also why Mail stayed empty for cases 1-7). Same-document
// JS has none of that — cases 1-7 now behave exactly like cases 8/9 already did: a direct function
// call injects the real notification the moment its step completes.
var CASE_SEQUENCES = {CASE_SEQUENCES_JSON};
var CASE_NOTIFS = {CASE_NOTIFS_JSON};
var CASE_GATE2 = {CASE_GATE2_JSON};
var currentExecCase = null;
var execToken = 0; // bumped on every Execute so a stale setTimeout from a prior run can't keep animating

function resetGraph(){{
  document.querySelectorAll('.vnode').forEach(function(n){{ n.classList.remove('active','complete'); }});
  document.querySelectorAll('.edge').forEach(function(e){{ e.classList.remove('lit','done'); }});
  document.getElementById('graph-log').innerHTML = '';
}}

function executeCase(n){{
  currentExecCase = n;
  execToken += 1;
  var myToken = execToken;
  clearMailForCase(n);
  resetGraph();
  document.getElementById('graph-caption').innerText = 'Case ' + n + ' — running the real recorded audit-log sequence below.';
  document.getElementById('exec-status-' + n).innerText = 'Running…';
  var sequence = CASE_SEQUENCES[n] || [];
  var notifs = CASE_NOTIFS[n] || [];
  var firedNotifIdx = {{}}; // trigger_agent -> next un-fired index, so a repeated agent doesn't double-fire
  var log = document.getElementById('graph-log');

  function fireNotifsFor(agentId){{
    notifs.forEach(function(notif, idx){{
      if(notif.trigger_agent === agentId && !firedNotifIdx[idx]){{
        firedNotifIdx[idx] = true;
        injectNotification(n, notif);
      }}
    }});
  }}

  function playGraph(i){{
    if(myToken !== execToken) return; // superseded by a newer Execute click
    if(i > 0){{
      var prevId = sequence[i-1].id;
      var prevEl = document.getElementById('vnode-' + prevId);
      if(prevEl){{ prevEl.classList.remove('active'); prevEl.classList.add('complete'); }}
      if(i < sequence.length){{
        var edgeEl = document.getElementById('edge_' + prevId + '__' + sequence[i].id);
        if(edgeEl){{ edgeEl.classList.add('lit','done'); }}
      }}
      fireNotifsFor(prevId);
      var logLine = document.createElement('div');
      logLine.textContent = '✓ ' + sequence[i-1].label + ' (' + sequence[i-1].duration_ms + 'ms)';
      log.appendChild(logLine);
    }}
    if(i >= sequence.length){{
      document.getElementById('exec-status-' + n).innerText = 'Executed this session — real audit-log replay complete.';
      return;
    }}
    var node = sequence[i];
    var el = document.getElementById('vnode-' + node.id);
    if(el) el.classList.add('active');
    if(i > 0){{
      var edgeEl2 = document.getElementById('edge_' + sequence[i-1].id + '__' + node.id);
      if(edgeEl2) edgeEl2.classList.add('lit');
    }}
    setTimeout(function(){{ playGraph(i+1); }}, 900);
  }}
  playGraph(0);
}}

function executeCase7(){{
  currentExecCase = 7;
  clearMailForCase(7);
  document.getElementById('exec-status-7').innerText = 'Evaluated by Agent 12 — awaiting PMO decision below.';
  document.getElementById('result-case7').style.display = 'none';
  document.getElementById('decision-case7').style.display = 'block';
}}
function case7Decide(choice){{
  var result = document.getElementById('result-case7');
  result.style.display = 'block';
  if(choice === 'Proceed'){{
    injectNotification(7, CASE7_NOTIF);
    result.innerText = 'Proceed — real notification delivered above (this matches actual Agent 12 auto-apply behavior).';
    document.getElementById('exec-status-7').innerText = 'Executed this session — Proceed confirmed, real notification delivered.';
  }} else {{
    result.innerText = choice + ' selected — preview only. The real pipeline has no code path to block a favorable, no-regression change here (it auto-applies with zero PMO touch time); shown for demo completeness.';
    document.getElementById('exec-status-7').innerText = 'Executed this session — ' + choice + ' selected (preview only, does not match real behavior).';
  }}
  toast('Gate 2 — ' + choice + ': Case 7 (Customer support AI triage)');
}}
function executeCase8(){{
  currentExecCase = 8;
  document.getElementById('exec-status-8').innerText = 'Evaluated by Agent 12 — awaiting PMO decision below.';
  document.getElementById('result-case8').style.display = 'none';
  document.getElementById('decision-case8').style.display = 'block';
}}
function case8Decide(choice){{
  var result = document.getElementById('result-case8');
  result.style.display = 'block';
  result.innerText = 'Gate 3 — ' + choice + ' (preview only — resolve_gate3() not called from here; same real change request shown in Projects → Needs Attention).';
  document.getElementById('exec-status-8').innerText = 'Executed this session — ' + choice + ' recorded (preview only).';
  toast('Gate 3 — ' + choice + ': Case 8 (Customer support AI triage) — see Projects → Needs Attention for the same real entry.');
}}

// ---- Cases 3/4/6: real Gate 2 decision cases. Execute plays the real prefix (Agents 1/2/Gate1/4/5/6
// up to the Gate 2 diamond) then stops and reveals the decision panel — Proceed/Reject/Hold each
// plays a real, distinct, pre-computed tail (Agent 7/9/10 on Proceed; Agent 8 on Reject) captured
// by _gate2_decision_case() in the build script from two separate real resume_after_gate2() runs.
function executeGate2Case(n){{
  currentExecCase = n;
  execToken += 1;
  var myToken = execToken;
  clearMailForCase(n);
  resetGraph();
  document.getElementById('graph-caption').innerText = 'Case ' + n + ' — running the real recorded audit-log sequence up to Gate 2.';
  document.getElementById('exec-status-' + n).innerText = 'Running…';
  document.getElementById('decision-case' + n).style.display = 'none';
  var resultEl = document.getElementById('result-case' + n);
  if(resultEl){{ resultEl.style.display = 'none'; resultEl.innerText = ''; }}
  var data = CASE_GATE2[n];
  var sequence = data.prefix;
  var notifs = data.prefix_notifs;
  var firedNotifIdx = {{}};
  var log = document.getElementById('graph-log');

  function fireNotifsFor(agentId){{
    notifs.forEach(function(notif, idx){{
      if(notif.trigger_agent === agentId && !firedNotifIdx[idx]){{
        firedNotifIdx[idx] = true;
        injectNotification(n, notif);
      }}
    }});
  }}

  function playPrefix(i){{
    if(myToken !== execToken) return;
    if(i > 0){{
      var prevId = sequence[i-1].id;
      var prevEl = document.getElementById('vnode-' + prevId);
      if(prevEl){{ prevEl.classList.remove('active'); prevEl.classList.add('complete'); }}
      if(i < sequence.length){{
        var edgeEl = document.getElementById('edge_' + prevId + '__' + sequence[i].id);
        if(edgeEl){{ edgeEl.classList.add('lit','done'); }}
      }}
      fireNotifsFor(prevId);
      var logLine = document.createElement('div');
      logLine.textContent = '✓ ' + sequence[i-1].label + ' (' + sequence[i-1].duration_ms + 'ms)';
      log.appendChild(logLine);
    }}
    if(i >= sequence.length){{
      document.getElementById('exec-status-' + n).innerText = 'Reached Gate 2 — awaiting PMO decision below.';
      if(n === 6) injectDraftComments(6);
      document.getElementById('decision-case' + n).style.display = 'block';
      return;
    }}
    var node = sequence[i];
    var el = document.getElementById('vnode-' + node.id);
    if(el) el.classList.add('active');
    if(i > 0){{
      var edgeEl2 = document.getElementById('edge_' + sequence[i-1].id + '__' + node.id);
      if(edgeEl2) edgeEl2.classList.add('lit');
    }}
    setTimeout(function(){{ playPrefix(i+1); }}, 900);
  }}
  playPrefix(0);
}}

function playGate2Tail(n, prevNodeId, tail, notifs, instant, onDone){{
  var myToken = execToken;
  var log = document.getElementById('graph-log');
  var firedNotifIdx = {{}};
  function fireNotifsFor(agentId){{
    notifs.forEach(function(notif, idx){{
      if(notif.trigger_agent === agentId && !firedNotifIdx[idx]){{
        firedNotifIdx[idx] = true;
        injectNotification(n, notif);
      }}
    }});
  }}
  function step(i){{
    if(myToken !== execToken) return;
    var prevId = (i > 0) ? tail[i-1].id : prevNodeId;
    if(i > 0){{
      var prevEl = document.getElementById('vnode-' + prevId);
      if(prevEl){{ prevEl.classList.remove('active'); prevEl.classList.add('complete'); }}
      fireNotifsFor(prevId);
      var logLine = document.createElement('div');
      logLine.textContent = '✓ ' + tail[i-1].label + ' (' + tail[i-1].duration_ms + 'ms)';
      log.appendChild(logLine);
    }}
    if(i >= tail.length){{
      if(onDone) onDone();
      return;
    }}
    var node = tail[i];
    if(prevId){{
      var edgeEl = document.getElementById('edge_' + prevId + '__' + node.id);
      if(edgeEl){{ edgeEl.classList.add('lit'); if(instant) edgeEl.classList.add('done'); }}
    }}
    var el = document.getElementById('vnode-' + node.id);
    if(el) el.classList.add(instant ? 'complete' : 'active');
    if(instant){{ step(i+1); }} else {{ setTimeout(function(){{ step(i+1); }}, 900); }}
  }}
  step(0);
}}

function gate2CaseDecide(n, choice){{
  var data = CASE_GATE2[n];
  var result = document.getElementById('result-case' + n);
  result.style.display = 'block';
  var lastPrefixId = data.prefix[data.prefix.length - 1].id;
  if(choice === 'Proceed'){{
    result.innerText = 'Proceed — running the real accept path (Agent 7/9/10)…';
    document.getElementById('exec-status-' + n).innerText = 'Running the real accept path…';
    playGate2Tail(n, lastPrefixId, data.accept_tail, data.accept_notifs, false, function(){{
      result.innerText = 'Proceed — real notification delivered above (matches actual Agent 7 accept behavior).';
      document.getElementById('exec-status-' + n).innerText = 'Executed this session — Proceed confirmed, real notification delivered.';
    }});
  }} else if(choice === 'Reject'){{
    playGate2Tail(n, lastPrefixId, data.reject_tail, data.reject_notifs, true, function(){{}});
    result.innerText = 'Reject — reason (AI-composed): "' + data.reject_reason + '" — real notification delivered instantly above.';
    document.getElementById('exec-status-' + n).innerText = 'Executed this session — Reject confirmed, real notification delivered instantly.';
  }} else {{
    result.innerText = 'Hold — no decision recorded. This project stays exactly where get_gate2_queue() already surfaces it (Projects → Queued Projects), to discuss at the next review — no notification is sent until PMO actually decides.';
    document.getElementById('exec-status-' + n).innerText = 'Executed this session — Hold selected, held for next review (no notification sent — matches real behavior).';
  }}
  toast('Gate 2 — ' + choice + ': Case ' + n);
}}

function clearMailForCase(n){{
  ['inbox','sent','draft'].forEach(function(folder){{
    document.querySelectorAll('#mail-list-' + folder + ' [data-case="' + n + '"]').forEach(function(el){{ el.remove(); }});
    refreshFolderEmptyState(folder);
  }});
}}

function restartWorkflowDemo(){{
  execToken += 1; // kill any in-flight animation
  currentExecCase = null;
  resetGraph();
  document.getElementById('graph-caption').innerText = 'Click Execute above to run this case\\'s real, audit-log-backed pipeline.';
  for(var i=1;i<=8;i++){{
    var status = document.getElementById('exec-status-' + i);
    if(status) status.innerText = 'Not yet executed this session.';
  }}
  ['inbox','sent','draft'].forEach(function(folder){{
    document.getElementById('mail-list-' + folder).innerHTML = '';
    refreshFolderEmptyState(folder);
  }});
  ['decision-case3','decision-case4','decision-case6','decision-case7','decision-case8'].forEach(function(id){{
    var panel = document.getElementById(id);
    if(panel) panel.style.display = 'none';
  }});
  ['result-case3','result-case4','result-case6','result-case7','result-case8'].forEach(function(id){{
    var el = document.getElementById(id);
    if(el){{ el.style.display = 'none'; el.innerText = ''; }}
  }});
  showCase(1);
  toast('↻ Demo restarted — all cases and Mail reset to a clean slate.');
}}

function refreshFolderEmptyState(folder){{
  var list = document.getElementById('mail-list-' + folder);
  var count = list.querySelectorAll('.notif-card').length;
  var empty = list.querySelector('.empty');
  if(count === 0 && !empty){{
    var div = document.createElement('div');
    div.className = 'empty';
    div.textContent = 'Nothing yet — execute a case in Live Workflow to see it arrive here.';
    list.appendChild(div);
  }} else if(count > 0 && empty){{
    empty.remove();
  }}
  document.getElementById('count-' + folder).textContent = count;
}}

function bumpBadge(folder){{
  var badge = document.getElementById('count-' + folder);
  badge.classList.remove('bump');
  void badge.offsetWidth; // restart animation
  badge.classList.add('bump');
}}

function mailCard(caseNum, tagLabel, subject, body, toLine){{
  var div = document.createElement('div');
  div.className = 'notif-card new';
  div.setAttribute('data-case', caseNum);
  div.innerHTML = '<div class="tag">CASE ' + caseNum + ' · ' + tagLabel + '</div>' +
    '<div class="subj"></div><div class="body"></div>' + (toLine ? '<div class="to"></div>' : '');
  div.querySelector('.subj').textContent = subject;
  div.querySelector('.body').textContent = body;
  if(toLine) div.querySelector('.to').textContent = toLine;
  return div;
}}

function injectNotification(caseNum, n){{
  var folder = (n.recipient === 'PMO Team') ? 'inbox' : 'sent';
  var tag = n.trigger_label || AGENT_LABELS[n.trigger_agent] || (n.trigger_agent || 'SYSTEM');
  var card = mailCard(caseNum, tag, n.subject, n.body, 'To: ' + n.recipient + ' · ' + n.channel);
  document.getElementById('mail-list-' + folder).prepend(card);
  refreshFolderEmptyState(folder);
  bumpBadge(folder);
  toast('\\uD83D\\uDCE7 New message in ' + (folder === 'inbox' ? 'Inbox' : 'Sent') + ' — Case ' + caseNum + ': ' + n.subject);
}}

function injectDraftComments(caseNum){{
  if(caseNum !== 6 || !CASE6_COMMENTS.length) return;
  CASE6_COMMENTS.forEach(function(c){{
    var subj = (c.is_flagged_concern ? '\\uD83D\\uDEA9 Flagged concern' : 'Comment') + (c.linked_gate ? ' · ' + c.linked_gate : '');
    var card = mailCard(caseNum, c.role.toUpperCase() + ' COMMENT — ' + c.author, subj, c.body, null);
    document.getElementById('mail-list-draft').prepend(card);
  }});
  refreshFolderEmptyState('draft');
  bumpBadge('draft');
  toast('\\uD83D\\uDCDD ' + CASE6_COMMENTS.length + ' PMO/stakeholder comment(s) landed in Draft — Case ' + caseNum);
}}

function toggleReview(id){{
  var panel = document.getElementById('decision-'+id);
  panel.style.display = (panel.style.display === 'block') ? 'none' : 'block';
}}
function decide(id, name, verdict){{
  var result = document.getElementById('result-'+id);
  result.innerText = 'Decision recorded: ' + verdict + ' (preview only — not written to the live DB from here)';
  result.style.display = 'block';
  toast(verdict + ' — ' + name + ' (preview only, no real Gate 2 write)');
}}
function gate3Decide(id, name, verdict){{
  var result = document.getElementById('result-gate3-'+id);
  result.innerText = 'Gate 3 decision: ' + verdict + ' (preview only — resolve_gate3() not called from here)';
  result.style.display = 'block';
  toast('Gate 3 — ' + verdict + ': ' + name + ' (preview only)');
}}
function flagForReview(projectId, projectName){{
  toast('Preview only — would run Agent 11 (capture) → Agent 12 (evaluate) on ' + projectName +
        '. Favorable changes auto-apply; anything that regresses risk/schedule/cost routes to Needs Attention, exactly like the real example above.');
}}
function showCase(n){{
  for(var i=1;i<=8;i++){{
    var pane = document.getElementById('case-pane-'+i);
    var btn = document.getElementById('case-btn-'+i);
    if(pane) pane.style.display = (i===n) ? 'block' : 'none';
    if(btn) btn.classList.toggle('active', i===n);
  }}
  execToken += 1; // invalidate any in-flight animation from the case being switched away from
  resetGraph();
  var caption = document.getElementById('graph-caption');
  if(caption) caption.innerText = (n <= 6)
    ? 'Click Execute above to run Case ' + n + '\\'s real, audit-log-backed pipeline.'
    : 'Cases 7-8 are post-acceptance updates — no node/edge graph for those (render_visualizer.py only covers agents 1-10, the intake path).';
}}

var DOC_KEYS = {json.dumps(DOC_KEYS_INITIAL)};
function showDoc(key){{
  DOC_KEYS.forEach(function(k){{
    document.getElementById('doc-pane-'+k).style.display = (k===key) ? 'block' : 'none';
    document.getElementById('doc-tab-'+k).classList.toggle('active', k===key);
  }});
}}
function saveDoc(key){{
  toast('Saved "' + key + '" for this preview session only — not written back to data/*.md.');
}}
function addDocument(){{
  var title = prompt('New document title (e.g. "Vendor Security Policy"):');
  if(!title || !title.trim()) return;
  docCounter += 1;
  var key = 'new' + docCounter;
  DOC_KEYS.push(key);

  var tabsRow = document.getElementById('doc-add-btn').parentNode;
  var tab = document.createElement('button');
  tab.className = 'case-btn';
  tab.id = 'doc-tab-' + key;
  tab.textContent = title.trim();
  tab.onclick = function(){{ showDoc(key); }};
  tabsRow.insertBefore(tab, document.getElementById('doc-add-btn'));

  var pane = document.createElement('div');
  pane.className = 'case-pane';
  pane.id = 'doc-pane-' + key;
  pane.style.display = 'none';
  pane.innerHTML = '<div class="panel"><h3>' + title.trim() + '</h3>' +
    '<div class="sub">Added this preview session — not written to disk, no source file backs this yet.</div>' +
    '<textarea class="field doc-editor" rows="18" placeholder="Write the document content here..."></textarea>' +
    '<div style="margin-top:10px;text-align:right"><button class="btn-ghost" onclick="saveDoc(\\'' + key + '\\')">Save</button></div></div>';
  document.getElementById('view-documents').appendChild(pane);

  showDoc(key);
  toast('Added "' + title.trim() + '" — session-only, not written to data/*.md.');
}}
function saveAgentSettings(btn){{
  var panel = btn.closest('.panel');
  var inputs = panel.querySelectorAll('input[data-key]');
  toast('Saved ' + inputs.length + ' value' + (inputs.length===1?'':'s') + ' for this preview session only — not written back to config.py.');
}}
function resetAgentSettings(btn){{
  var panel = btn.closest('.panel');
  var inputs = panel.querySelectorAll('input[data-default]');
  inputs.forEach(function(inp){{ inp.value = inp.getAttribute('data-default'); }});
  toast('Reset ' + inputs.length + ' value' + (inputs.length===1?'':'s') + ' to the recommended default.');
}}
</script>
</body></html>"""

out_path = os.path.join(OUT_DIR, "dashboard_preview.html")
with open(out_path, "w") as f:
    f.write(html_out)
print("wrote", out_path)
print("total_projects", total_projects, "portfolio_value", portfolio_value, "approved_rate", approved_rate,
      "avg_success", avg_success, "needs_attention", len(needs_attention))
