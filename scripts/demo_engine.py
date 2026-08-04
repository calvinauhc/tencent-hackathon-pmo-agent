"""
Shared demo engine — the ONE place that seeds the DB, runs a named scenario through the real
pipeline, and renders all five dashboard pages. Both the CLI entry point (scripts/run_demo.py) and
the in-browser composer server (scripts/demo_server.py) import this, so there is exactly one code
path for "run a scenario" rather than two copies that can drift apart.

Also holds SCENARIO_EMAILS — predrafted submission text for each of the 7 named scenarios in
data/trial-projects.json's scenario_index (§12), phrased as a real submitter would write it, built
from that scenario's real trial-data fields (not fabricated). This is what the composer landing
page (dashboard's entry point, §12.1) shows and lets you click to run.
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import (
    insert_project, write_comment, get_project, get_project_by_ref, get_project_updates,
    get_change_request, update_status, get_gate2_queue, get_open_gate2_batch, open_gate2_batch,
    close_gate2_batch, get_latest_agent_payload,
)
from src.shared.schemas import Project
from src.shared.config import GATE2_FAST_TRACK_CAPEX_USD
from src.db.trial_loader import load_trial_data
from src.orchestration.pipeline import run_submission, run_intake_to_gate2, resume_after_gate2
from src.agents.agent1_intake_parser import parse_intake
from src.orchestration.state_machine import transition
from src.agents.agent11_update_logger import log_update
from src.agents.agent12_change_evaluator import process_update, resolve_gate3
from src.agents.agent13_opl_composer import compose_opl, publish_opl
from src.shared.schemas import Status
from dashboard.render_topline import render as render_topline
from dashboard.render_visualizer import render as render_visualizer
from dashboard.render_comments import render as render_comments
from dashboard.render_notifications import render as render_notifications
from dashboard.render_activity import render as render_activity
from dashboard.render_gate2 import render as render_gate2
from dashboard.render_gate3 import render as render_gate3
from dashboard.render_opl import render as render_opl_page
from dashboard.render_gate2_queue import render as render_gate2_queue

SCENARIO_MOCKS = {
    "1_accepted_aligned_low_capex_high_price": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
    },
    "2_rejected_duplicate_exists": {
        "agent2_adjudication": {"same_project": True, "rationale": "Same pain point and solution, different project name."},
    },
    "3_rejected_misaligned_business_direction": {
        "agent5": {"margin_impact": "unclear", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "misaligned", "citation": "Consumer-facing new product lines outside existing verticals"},
    },
    "4_under_review_unknown_regulatory_risk": {
        "agent5": {"margin_impact": "unclear", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "inconclusive", "citation": "unknown or unquantified regulatory risk defaults to"},
    },
    "6_change_request_stakeholder_flag": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "proposals silent on data handling are treated as incomplete, not compliant-by-default"},
    },
    "7_borderline_duplicate_llm_adjudication": {
        "agent2_adjudication": {"same_project": False, "rationale": "Different processes (inbound vs outbound timing)."},
        "agent5": {"margin_impact": "unclear", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
    },
}

PROJECT_001_EMAIL = (
    "Hi PMO team, I would like to propose this project 001. The objective is to generate a size "
    "of price of 0.5 million USD and the estimated budget needed is 100,000 USD. There is no "
    "regulatory risk in implementation, however we need to wait for the approval before live. "
    "Let me know your thoughts."
)

SCENARIO_EMAILS = {
    "1_accepted_aligned_low_capex_high_price": {
        "from": "Grace Lim <grace.lim@company.com>", "subject": "Proposal: Customer support AI triage",
        "body": "Hi PMO team,\n\nI'd like to submit a proposal: Customer support AI triage.\n\n"
                "Objective: Customer support tickets take too long to triage and route.\n"
                "Proposed solution: An automated triage and routing layer built on existing ticketing data.\n\n"
                "Estimated business impact: $220,000. Estimated CAPEX: $60,000 (fully funded).\n"
                "Expected launch: October 2026.\n"
                "Risk: No significant risk identified at this stage.\n\n"
                "Team: Grace Lim, Daniel Ho — Sales, Southeast Asia.\n\nThanks,\nGrace",
    },
    "2_rejected_duplicate_exists": {
        "from": "Fatima Rahman <fatima.rahman@company.com>", "subject": "Proposal: Early stock-out warning system",
        "body": "Hi PMO team,\n\nSubmitting a new proposal: Early stock-out warning system.\n\n"
                "Objective: Warehouse teams have no early warning before stock runs out.\n"
                "Proposed solution: A predictive model that flags the issue before it becomes critical.\n\n"
                "Estimated business impact: $145,000. Estimated CAPEX: $38,000.\n"
                "Expected launch: January 2027.\n"
                "Risk: Dependency on a third-party API with uncertain uptime.\n\n"
                "Team: Fatima Rahman — Operations, North America.\n\nThanks,\nFatima",
    },
    "3_rejected_misaligned_business_direction": {
        "from": "Omar Hassan <omar.hassan@company.com>", "subject": "Proposal: Consumer subscription box pilot",
        "body": "Hi PMO team,\n\nI'd like to propose a new product line: Consumer subscription box pilot.\n\n"
                "Objective: We want to launch a new consumer subscription box product line.\n"
                "Proposed solution: A new direct-to-consumer product line and fulfillment operation.\n\n"
                "Estimated business impact: $400,000. Estimated CAPEX: $180,000.\n"
                "Expected launch: August 2027.\n"
                "Risk: Dependency on a third-party API with uncertain uptime.\n\n"
                "Team: Omar Hassan, Ingrid Larsen — Marketing.\n\nThanks,\nOmar",
    },
    "4_under_review_unknown_regulatory_risk": {
        "from": "Elena Petrova <elena.petrova@company.com>", "subject": "Proposal: Regulatory reporting automation",
        "body": "Hi PMO team,\n\nProposal: Regulatory reporting automation.\n\n"
                "Objective: Regulatory filings are compiled manually and are error-prone.\n"
                "Proposed solution: A structured drafting and review agent for compliance documents.\n\n"
                "Estimated business impact: $150,000. Estimated CAPEX: $35,000.\n"
                "Expected launch: May 2027 (pending confirmation of regulatory scope).\n"
                "Risk: Unclear regulatory exposure in target region — scope of automated filing not yet "
                "confirmed with counsel.\n\nTeam: Elena Petrova — Regulatory, Europe.\n\nThanks,\nElena",
    },
    "5_rejected_incomplete_information": {
        "from": "(unsigned)", "subject": "project 001", "body": PROJECT_001_EMAIL,
    },
    "6_change_request_stakeholder_flag": {
        "from": "Jane Tan <jane.tan@company.com>", "subject": "Proposal: Smart inventory forecasting agent",
        "body": "Hi PMO team,\n\nProposal: Smart inventory forecasting agent.\n\n"
                "Objective: Regional warehouses run out of stock unpredictably, causing lost sales.\n"
                "Proposed solution: AI agent that predicts stock-outs two weeks ahead using sales and "
                "supplier lead-time data.\n\nEstimated business impact: $180,000. Estimated CAPEX: $40,000 "
                "(fully funded).\nExpected launch: November 2026.\n"
                "Risk: Requires change management across multiple teams.\n\n"
                "Team: Jane Tan, Alex Ong, Priya Nair — Operations, Southeast Asia.\n\nThanks,\nJane",
    },
    "7_borderline_duplicate_llm_adjudication": {
        "from": "Sofia Garcia <sofia.garcia@company.com>", "subject": "Proposal: Supplier delivery timing accuracy agent",
        "body": "Hi PMO team,\n\nProposal: Supplier delivery timing accuracy agent.\n\n"
                "Objective: Supplier lead times are sometimes unpredictable and this can cause delays.\n"
                "Proposed solution: A forecasting agent trained on historical and supplier data.\n\n"
                "Estimated business impact: $295,000. Estimated CAPEX: $110,000.\n"
                "Expected launch: April 2027.\n\n"
                "Team: Sofia Garcia — Engineering, North America.\n\nThanks,\nSofia",
    },
}

SCENARIO_META = {
    "1_accepted_aligned_low_capex_high_price": {"title": "Aligned, low CAPEX / high price", "outcome": "Expected: Accepted"},
    "2_rejected_duplicate_exists": {"title": "Duplicate of an existing project", "outcome": "Expected: Rejected — duplicate"},
    "3_rejected_misaligned_business_direction": {"title": "Misaligned with business direction", "outcome": "Expected: Rejected — misaligned"},
    "4_under_review_unknown_regulatory_risk": {"title": "Unknown regulatory risk", "outcome": "Expected: Under review — inconclusive"},
    "5_rejected_incomplete_information": {"title": "Incomplete information at intake", "outcome": "Expected: Rejected at Agent 1 — incomplete"},
    "6_change_request_stakeholder_flag": {"title": "Accepted, then stakeholder flags a concern", "outcome": "Expected: Accepted → Gate 3 change-management trigger"},
    "7_borderline_duplicate_llm_adjudication": {"title": "Borderline similarity — LLM adjudicates", "outcome": "Expected: Not a duplicate → proceeds to Accepted"},
}

def _result_id(project, trace):
    """The real DB key this run's audit_log/notification rows were written under — matches
    src/orchestration/pipeline.py's _log_step exactly (project.project_id or project.submission_id).
    trace["project_id"] is only set on the accept branch of resume_after_gate2(); for every other
    outcome (rejected, duplicate, misaligned, inconclusive), falling back straight to
    project.submission_id is wrong whenever the trial-data anchor already carries a pre-assigned
    project_id (several do, e.g. ones reused as "existing accepted projects" for duplicate checks
    in other scenarios) — that pre-assigned id is what _log_step actually used, not the submission
    id, so rendering under the wrong one reads back an empty trace."""
    return trace.get("project_id") or project.project_id or project.submission_id


SCENARIO_ORDER = [
    "1_accepted_aligned_low_capex_high_price", "2_rejected_duplicate_exists",
    "3_rejected_misaligned_business_direction", "4_under_review_unknown_regulatory_risk",
    "5_rejected_incomplete_information", "6_change_request_stakeholder_flag",
    "7_borderline_duplicate_llm_adjudication",
]


def run_scenario(scenario_key):
    """Seeds all trial projects, runs one scenario through the real pipeline, renders all five
    dashboard pages, and returns a dict describing what happened and where to look."""
    conn = get_connection(fresh=True)
    projects, idx = load_trial_data()
    by_id = {p.submission_id: p for p in projects}
    by_pid = {p.project_id: p for p in projects if p.project_id}
    def get(ref): return by_pid.get(ref) or by_id.get(ref)

    for p in projects:
        insert_project(conn, p)

    ref = idx[scenario_key]
    target = get(ref[1] if isinstance(ref, list) else ref)
    existing = [p for p in projects if p.status in ("accepted", "in_progress", "completed") and p.submission_id != target.submission_id]
    mocks = SCENARIO_MOCKS.get(scenario_key, {})
    trace = run_submission(conn, target, existing, mocks)
    result_id = _result_id(target, trace)

    if scenario_key == "6_change_request_stakeholder_flag":
        write_comment(conn, result_id, "Priya Sharma", "pmo",
                      "Accept — confirm data handling plan before launch.",
                      is_flagged_concern=False, linked_gate="gate2")
        write_comment(conn, result_id, "Wei Ling Tan", "regulatory",
                      "This touches EU customer data — confirm a GDPR review is scheduled before go-live.",
                      is_flagged_concern=True, linked_gate=None)

    t_path, t_count = render_topline()
    v_path, v_steps = render_visualizer(result_id)
    c_path, c_count = render_comments(result_id)
    n_path, n_count = render_notifications(result_id)
    a_path, a_count = render_activity()

    return {
        "scenario_key": scenario_key,
        "trace": trace,
        "result_id": result_id,
        "paths": {
            "topline": t_path, "visualizer": v_path, "comments": c_path,
            "notifications": n_path, "activity": a_path,
        },
        "counts": {"projects": t_count, "steps": v_steps, "comments": c_count,
                   "notifications": n_count, "activity": a_count},
    }


def _render_all(result_id, resume_from=None):
    t_path, t_count = render_topline()
    v_path, v_steps = render_visualizer(result_id, resume_from=resume_from)
    c_path, c_count = render_comments(result_id)
    n_path, n_count = render_notifications(result_id)
    a_path, a_count = render_activity()
    return {
        "paths": {"topline": t_path, "visualizer": v_path, "comments": c_path,
                  "notifications": n_path, "activity": a_path},
        "counts": {"projects": t_count, "steps": v_steps, "comments": c_count,
                   "notifications": n_count, "activity": a_count},
    }


def run_scenario_to_gate2(scenario_key):
    """
    Two-phase version used by the in-browser composer (scripts/demo_server.py) — runs everything
    up to Manual Gate 2 and stops there for real. If the scenario terminates before Gate 2 anyway
    (duplicate, incomplete, Gate 1 reject, or Agent 6 inconclusive), it renders the dashboards and
    returns a "terminal" result exactly like run_scenario() would. Otherwise it renders the Gate 2
    decision page and returns "pending_gate2" with everything needed to resume once a real PMO
    decision is made.
    """
    conn = get_connection(fresh=True)
    projects, idx = load_trial_data()
    by_id = {p.submission_id: p for p in projects}
    by_pid = {p.project_id: p for p in projects if p.project_id}
    def get(ref): return by_pid.get(ref) or by_id.get(ref)

    for p in projects:
        insert_project(conn, p)

    ref = idx[scenario_key]
    target = get(ref[1] if isinstance(ref, list) else ref)
    existing = [p for p in projects if p.status in ("accepted", "in_progress", "completed") and p.submission_id != target.submission_id]
    mocks = SCENARIO_MOCKS.get(scenario_key, {})
    trace = run_intake_to_gate2(conn, target, existing, mocks)

    if trace.get("final_status") == "pending_gate2":
        g_path = render_gate2(target.submission_id, target, trace)
        # Render the visualizer for the partial trace too (Agents 1,2,4,5,6 + Gate 1), with
        # redirect_to pointed at the Gate 2 page — the composer sends the PMO here FIRST so the
        # steps actually play out in sequence, then it auto-forwards to the real decision page
        # instead of jumping straight there (see scripts/demo_server.py's /run/<key> handler).
        gate2_file = f"gate2_{target.submission_id}.html"
        # audit_log/notification rows for this run are keyed by whatever ID src/orchestration/
        # pipeline.py's _log_step actually used (project.project_id or project.submission_id) — some
        # trial-data anchors (e.g. this one) already carry a pre-assigned project_id even before
        # Gate 2 has been decided, so the visualizer must be rendered under THAT id or it reads back
        # an empty trace.
        visualizer_id = _result_id(target, trace)
        v_path, v_steps = render_visualizer(visualizer_id, redirect_to=gate2_file)
        return {
            "status": "pending_gate2",
            "submission_id": target.submission_id,
            "visualizer_id": visualizer_id,
            "scenario_key": scenario_key,
            "project": target,
            "trace": trace,
            "paths": {"gate2": g_path, "visualizer": v_path},
        }

    result_id = _result_id(target, trace)
    rendered = _render_all(result_id)
    return {"status": "terminal", "scenario_key": scenario_key, "trace": trace, "result_id": result_id, **rendered}


def resume_scenario(project, trace, gate2_decision, scenario_key=None, override_reason=None, pmo_comment="",
                     gate2_batch_id=None, exception_reason=None):
    """Phase 2 of the composer flow — takes the real PMO decision made on the Gate 2 page and
    completes the pipeline (Agent 7/9/10 on accept, Agent 8 on reject). Uses the same DB the
    scenario was seeded into during run_scenario_to_gate2() (not fresh — this continues that run,
    it doesn't start a new one). `override_reason`/`pmo_comment` come straight from the PMO's edits
    on the Gate 2 reject form, if this is a rejection. `gate2_batch_id`/`exception_reason` (§5.3)
    carry through from wherever this decision was actually invited — an open batch sitting, a
    logged PMO override, or neither (cases 1–7's immediate/demo-mode path)."""
    conn = get_connection()
    trace = resume_after_gate2(conn, project, trace, gate2_decision, override_reason=override_reason,
                                pmo_comment=pmo_comment, gate2_batch_id=gate2_batch_id, exception_reason=exception_reason)
    result_id = _result_id(project, trace)

    if scenario_key == "6_change_request_stakeholder_flag" and trace["final_status"] not in ("rejected",):
        write_comment(conn, result_id, "Priya Sharma", "pmo",
                      "Accept — confirm data handling plan before launch.",
                      is_flagged_concern=False, linked_gate="gate2")
        write_comment(conn, result_id, "Wei Ling Tan", "regulatory",
                      "This touches EU customer data — confirm a GDPR review is scheduled before go-live.",
                      is_flagged_concern=True, linked_gate=None)

    # resume_from="gate2" — the PMO already watched Agents 1-6/Gate 1 animate during the partial
    # render before this decision (see run_scenario_to_gate2), so this replay fast-forwards through
    # that part and continues straight into whatever's actually new: Agent 7-10 on accept, Agent 8
    # on reject.
    rendered = _render_all(result_id, resume_from="gate2")
    render_gate2_queue()  # §5.3 — this project (if it came from the queue) should no longer list there
    return {"trace": trace, "result_id": result_id, **rendered}


# --- §7.2 post-acceptance change management (Agents 11/12) — Phase 2 ---
# Two canned demo payloads against Case 1's already-accepted project (SUB-0001/PRJ-2026-0791, seeded
# as `status: accepted` directly in trial-projects.json — no need to "run" it first). One improves
# every governance axis it touches (auto-applies, Agent 12 favorable path); the other regresses on
# risk even though CAPEX is a little worse too, so it's unambiguous which path each one takes.
CHANGE_DEMO_PAYLOADS = {
    "favorable": {
        "capex_usd": 55000, "expected_launch_date": "2026-09-15",
        "submitted_by": "Grace Lim",
        "note": "Vendor quote came in under budget; pulled the launch date in by a month.",
    },
    "unfavorable": {
        "capex_usd": 85000, "risk_indicator": "yellow",
        "submitted_by": "Grace Lim",
        "note": "Integration scope grew after vendor discovery; flagging a new dependency risk and revised CAPEX.",
    },
}

def _ensure_seeded(conn, project_ref):
    """The composer's DB only has whatever the last /run/<scenario> call inserted (fresh=True wipes
    it each time) — if no scenario has been run yet this session, `projects` may be empty. Load the
    trial fixture (idempotent, INSERT OR REPLACE) so a change-management demo works standalone,
    without requiring "run Case 1" first. If the project was already touched live this session
    (e.g. Case 1 was actually run and accepted through the composer), this never overwrites that —
    it only fills in what's missing."""
    row = get_project_by_ref(conn, project_ref)
    if row is not None:
        return row
    projects, _idx = load_trial_data()
    for p in projects:
        insert_project(conn, p)
    return get_project_by_ref(conn, project_ref)

def submit_project_update(project_ref, kind):
    """Runs Agent 11 (capture) then Agent 12 (evaluate + apply-or-escalate) against a live project.
    `kind` selects one of the two canned CHANGE_DEMO_PAYLOADS. Returns where the composer should
    send the middle panel next: straight to the (now-updated) topline dashboard if it auto-applied,
    or to a real Gate 3 review page if it didn't."""
    if kind not in CHANGE_DEMO_PAYLOADS:
        return {"error": f"Unknown change kind '{kind}'"}
    conn = get_connection()
    row = _ensure_seeded(conn, project_ref)
    if row is None:
        return {"error": f"Unknown project '{project_ref}'"}

    payload = CHANGE_DEMO_PAYLOADS[kind]
    submitted_fields = {k: v for k, v in payload.items() if k not in ("submitted_by", "note")}
    entry = log_update(conn, row, submitted_fields, submitted_by=payload["submitted_by"], note=payload["note"])
    result = process_update(conn, entry, row["project_name"], requested_by=payload["submitted_by"])

    render_topline()
    render_activity()

    if result["applied"]:
        return {"applied": True, "evaluation": result["evaluation"], "reason": result["reason"],
                "redirect": "/dashboard/topline.html"}

    cr = get_change_request(conn, result["change_request_id"])
    gate3_path = render_gate3(result["change_request_id"], row, entry, cr)
    return {"applied": False, "evaluation": result["evaluation"], "reason": result["reason"],
            "change_request_id": result["change_request_id"],
            "redirect": f"/dashboard/gate3_{result['change_request_id']}.html"}

def resolve_gate3_decision(change_request_id, decision, pmo_comment=""):
    """Phase 2 of the Gate 3 flow — takes the real PMO decision from the Gate 3 page and applies or
    declines the change. Uses the same DB the change was captured into (not fresh)."""
    conn = get_connection()
    cr = get_change_request(conn, change_request_id)
    if cr is None:
        return {"error": f"Unknown change_request_id {change_request_id}"}
    project = get_project_by_ref(conn, cr["original_project_id"])
    project_name = project["project_name"] if project else cr["original_project_id"]
    try:
        result = resolve_gate3(conn, change_request_id, decision, project_name, pmo_comment=pmo_comment)
    except ValueError as e:
        # Already resolved (refresh, double-click, the page re-submitting) — same idempotency
        # concern /gate2/'s RESOLVED dict handles, but here the change_requests row itself already
        # carries its own resolved state, so re-reading it is enough; no separate in-memory map needed.
        return {"redirect": "/dashboard/topline.html", "status": cr["status"], "note": str(e)}
    render_topline()
    render_activity()
    return {"redirect": "/dashboard/topline.html", **result}


# --- §7.2.3 Agent 13 (OPL Composer) — Phase 3 ---
# Canned mock grounded in Case 1's own real history — the two demo change-management submissions
# (CHANGE_DEMO_PAYLOADS above), whichever of them actually landed on this project by the time this
# runs. If neither ran yet, Agent 13 still composes something (just thinner source material — the
# original intake/acceptance trail is real content too), but this mock reads best after both.
OPL_DEMO_MOCK = {
    "objective": "Customer support tickets take too long to triage and route.",
    "solution": "An automated triage and routing layer built on existing ticketing data.",
    "timeline_narrative": "A vendor quote came in under budget, so the team pulled the launch date "
        "in by a month. Scope then grew after vendor discovery, raising CAPEX and flagging a new "
        "dependency risk — PMO reviewed that change at Gate 3 and authorized it.",
    "outcome": "Delivered under a PMO-authorized, revised budget and timeline; the elevated risk was "
        "accepted knowingly rather than discovered late.",
    "what_worked": "Getting a vendor quote early, before locking the launch date, bought real "
        "schedule flexibility. Worth requesting a vendor quote up front on similar automation "
        "projects before committing to a date.",
    "citations": [
        "Vendor quote came in under budget; pulled the launch date in by a month.",
        "Integration scope grew after vendor discovery; flagging a new dependency risk and revised CAPEX.",
    ],
}

def complete_project(project_ref, mock_response=None):
    """Demo trigger for Agent 13 — transitions a project to `completed` (bridging accepted ->
    in_progress -> completed if needed, same as a real project would move through those states) and
    composes + publishes its OPL. Uses whatever real project_updates/change_requests/audit_log
    history the project already has (§7.2.3's source material) — running this after the Phase 2
    change-management demo buttons gives Agent 13 real content to cite, not just the bare intake trail."""
    conn = get_connection()
    row = get_project_by_ref(conn, project_ref)
    if row is None:
        return {"error": f"Unknown project '{project_ref}'"}

    status = row["status"]
    if status not in (Status.ACCEPTED.value, Status.IN_PROGRESS.value, Status.COMPLETED.value):
        return {"error": f"Project '{project_ref}' is status={status}; can only complete an "
                          f"accepted or in_progress project."}

    if status == Status.ACCEPTED.value:
        update_status_chain = [Status.IN_PROGRESS.value, Status.COMPLETED.value]
    elif status == Status.IN_PROGRESS.value:
        update_status_chain = [Status.COMPLETED.value]
    else:
        update_status_chain = []  # already completed — just (re)compose the OPL

    cur_status = status
    for target in update_status_chain:
        update_status(conn, row["submission_id"], transition(cur_status, target))
        cur_status = target

    row = get_project_by_ref(conn, project_ref)  # refresh after the status transition(s)
    project_id = row["project_id"] or row["submission_id"]
    composed, _dur = compose_opl(conn, row, mock_response=mock_response or OPL_DEMO_MOCK)
    opl_path = publish_opl(conn, row, composed)
    render_opl_page(project_id, row, composed)

    render_topline()
    render_activity()

    return {"applied": True, "opl_path": opl_path, "dropped_ungrounded": composed.get("dropped_ungrounded", 0),
            "redirect": f"/dashboard/opl_{project_id}.html"}


# --- §5.3 periodic Gate 2 review (cases 8/9/10) ---
BATCH_CASE_PROJECTS = {
    "8a": Project(
        submission_id="SUB-CASE8A", submitter_name="Nadia Suryani", team_members=["Nadia Suryani", "Budi Santoso"],
        objective="Regional demand spikes catch inventory planning off guard, causing stockouts",
        project_name="Regional demand forecasting agent",
        solution="An ML-based demand forecasting layer integrated with existing inventory and sales data",
        business_impact_usd=420000, expected_launch_date="2026-12-01",
        hypothesis_risk="No significant risk identified at this stage", risk_category="operational",
        capex_usd=300000, capex_funded_pct=100, region="Southeast Asia", business_unit="Sales",
    ),
    "8b": Project(
        submission_id="SUB-CASE8B", submitter_name="Kiet Tran", team_members=["Kiet Tran", "Mei Lin Goh"],
        objective="Cross-border shipments routinely miss customs windows, delaying delivery",
        project_name="Cross-border logistics optimizer",
        solution="A route optimization and customs-document automation layer for regional freight",
        business_impact_usd=380000, expected_launch_date="2027-01-15",
        hypothesis_risk="No significant risk identified at this stage", risk_category="operational",
        capex_usd=280000, capex_funded_pct=100, region="Southeast Asia", business_unit="Operations",
    ),
    "9": Project(
        submission_id="SUB-CASE9", submitter_name="Alex Rivera", team_members=["Alex Rivera"],
        objective="Internal IT helpdesk tickets take too long to triage manually",
        project_name="Helpdesk triage chatbot pilot",
        solution="A lightweight chatbot pilot to auto-triage common helpdesk requests",
        business_impact_usd=80000, expected_launch_date="2026-11-01",
        hypothesis_risk="No significant risk identified at this stage", risk_category="operational",
        capex_usd=35000, capex_funded_pct=100, region="North America", business_unit="Engineering",
    ),
    "10": Project(
        submission_id="SUB-CASE10", submitter_name="Elin Berger", team_members=["Elin Berger", "Marco Rossi"],
        objective="An upcoming GDPR consent-audit deadline requires a faster review process than manual spreadsheets allow",
        project_name="GDPR consent-audit automation",
        solution="An automated consent-audit trail and reporting layer for EU customer data handling",
        business_impact_usd=260000, expected_launch_date="2026-10-01",
        hypothesis_risk="Regulatory deadline within the quarter; delay risk if not prioritized", risk_category="regulatory",
        capex_usd=120000, capex_funded_pct=100, region="Europe", business_unit="Regulatory",
    ),
}

BATCH_CASE_MOCKS = {
    "8a": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
    },
    "8b": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
    },
    "9": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
    },
    "10": {
        "agent5": {"margin_impact": "positive", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
        "agent6": {"verdict": "aligned", "citation": "Europe (only for regulatory/compliance-driven projects)"},
    },
}

BATCH_CASE_META = {
    "8a": {"title": "Case 8a — Southeast Asia budget, project A", "outcome": "Lands in the Gate 2 queue"},
    "8b": {"title": "Case 8b — Southeast Asia budget, project B", "outcome": "Lands in the Gate 2 queue, competing with 8a for the same budget"},
    "9": {"title": "Case 9 — Fast-track exception (<$50K)", "outcome": "Skips the queue, opens Gate 2 immediately"},
    "10": {"title": "Case 10 — PMO manual override candidate", "outcome": "Lands in the queue; pull it out early with a logged reason"},
}


def is_fast_track(project):
    capex = project.capex_usd if hasattr(project, "capex_usd") else project.get("capex_usd")
    return (capex or 0) < GATE2_FAST_TRACK_CAPEX_USD


def _row_to_project(row):
    """Rebuilds a Project object from a DB row dict — render_gate2()/resume_after_gate2() expect
    attribute access, not dict access (§5.3's queue reads rows back from the DB, not from an
    in-memory trace kept around the whole time a project waits)."""
    data = dict(row)
    if isinstance(data.get("team_members"), str):
        try:
            data["team_members"] = json.loads(data["team_members"])
        except (TypeError, ValueError):
            data["team_members"] = []
    allowed = set(Project.__dataclass_fields__.keys())
    return Project(**{k: v for k, v in data.items() if k in allowed})


def _reconstruct_gate2_trace(conn, submission_id):
    """§5.3 — a queued project's Agent 5/6 findings aren't kept in server memory (PENDING) the
    whole time it waits; rebuild them from audit_log on demand, the moment a PMO actually pulls it
    out to decide (via the batch or an override)."""
    row = get_project(conn, submission_id)
    if row is None:
        return None, None, f"Unknown project '{submission_id}'."
    if row["status"] != "analysis":
        return None, None, f"'{submission_id}' is not currently in the Gate 2 queue (status={row['status']})."
    pid = row["project_id"] or submission_id
    a5 = get_latest_agent_payload(conn, pid, "agent5_business_impact")
    a6 = get_latest_agent_payload(conn, pid, "agent6_knowledge_crosscheck")
    if a5 is None or a6 is None:
        return None, None, f"Could not reconstruct Agent 5/6 findings for '{submission_id}'."
    project = _row_to_project(row)
    trace = {"submission_id": submission_id, "steps": [], "notifications": [],
              "agent5": a5, "agent6": a6, "final_status": "pending_gate2"}
    return project, trace, None


def run_batch_case(case_key):
    """§5.3 demo entry point for cases 8/9/10. Runs a synthetic project through intake->Gate1->
    Agent5/6 (pipeline unchanged, §2) and then either opens Gate 2 immediately (fast-track, <$50K)
    or lands it in the queue (everything else) — the composer decides nothing here that the real
    §5.3 rule doesn't already decide."""
    if case_key not in BATCH_CASE_PROJECTS:
        return {"error": f"Unknown batch case '{case_key}'"}
    conn = get_connection()
    project = BATCH_CASE_PROJECTS[case_key]

    existing_row = get_project(conn, project.submission_id)
    if existing_row is not None:
        # Already run earlier this session (re-clicking the button) — report where it currently
        # stands instead of re-running the pipeline against an already-progressed project.
        if existing_row["status"] == "analysis":
            render_gate2_queue()
            return {"redirect": "/dashboard/gate2_queue.html"}
        return {"redirect": "/dashboard/topline.html"}

    mocks = BATCH_CASE_MOCKS[case_key]
    trace = run_intake_to_gate2(conn, project, [], mocks)
    render_topline()
    render_activity()
    if trace.get("final_status") != "pending_gate2":
        return {"redirect": "/dashboard/topline.html"}

    if is_fast_track(project):
        render_gate2(project.submission_id, project, trace)
        visualizer_id = _result_id(project, trace)
        render_visualizer(visualizer_id, redirect_to=f"gate2_{project.submission_id}.html")
        return {
            "queued": False, "submission_id": project.submission_id, "project": project, "trace": trace,
            "exception_reason": f"policy: CAPEX under ${GATE2_FAST_TRACK_CAPEX_USD:,.0f} fast-track threshold",
            "redirect": f"/dashboard/visualizer_{visualizer_id}.html",
        }

    render_gate2_queue()
    return {"queued": True, "submission_id": project.submission_id, "redirect": "/dashboard/gate2_queue.html"}


def review_queued_project(submission_id):
    """PMO reviews a queued project as part of the currently open weekly batch sitting (§5.3) —
    requires a batch to actually be open, so this stays a real periodic review rather than an
    immediate decision with an extra click in front of it."""
    conn = get_connection()
    batch = get_open_gate2_batch(conn)
    if batch is None:
        return {"error": "No batch is currently open — open this week's batch first."}
    project, trace, err = _reconstruct_gate2_trace(conn, submission_id)
    if err:
        return {"error": err}
    render_gate2(submission_id, project, trace)
    return {"project": project, "trace": trace, "gate2_batch_id": batch["id"], "exception_reason": None,
            "redirect": f"/dashboard/gate2_{submission_id}.html"}


def override_queued_project(submission_id, reason):
    """§5.3's logged PMO override — pulls a project out of the queue early without waiting for (or
    requiring) an open batch sitting. Narrow by design: every use carries the PMO's own stated
    reason, which is what the topline dashboard's exception-rate metric reads."""
    if not (reason or "").strip():
        return {"error": "An override reason is required."}
    conn = get_connection()
    project, trace, err = _reconstruct_gate2_trace(conn, submission_id)
    if err:
        return {"error": err}
    render_gate2(submission_id, project, trace)
    return {"project": project, "trace": trace, "gate2_batch_id": None, "exception_reason": reason.strip(),
            "redirect": f"/dashboard/gate2_{submission_id}.html"}


def open_batch():
    conn = get_connection()
    if get_open_gate2_batch(conn) is None:
        open_gate2_batch(conn, opened_by="PMO")
    render_gate2_queue()
    return {"redirect": "/dashboard/gate2_queue.html"}


def close_batch(batch_id):
    conn = get_connection()
    close_gate2_batch(conn, batch_id)
    render_gate2_queue()
    return {"redirect": "/dashboard/gate2_queue.html"}


# --- Freeform "compose your own" submission (§12.1 composer, "comparing Foo's repo" upversion) ---
# Same real pipeline as the 7 named cases, but starting from raw From/Subject/Body text a person
# actually typed instead of a predrafted trial-data anchor. Uses Agent 1's parse_intake() — the
# genuine "parse raw text" entry point (src/agents/agent1_intake_parser.py), which the named-case
# path never needed because trial data arrives pre-structured. In MOCK_MODE (no ANTHROPIC_API_KEY,
# the demo default) parse_intake() falls back to its deterministic regex extractor rather than
# raising, so a submission whose fields don't match the expected email shape (see the compose box's
# placeholder template) comes back with those fields genuinely None — which then correctly routes
# through the same "incomplete information" rejection Case 5 demonstrates, not a crash.
#
# Agent 5/6 have no deterministic fallback of their own (only Agent 1 does — see that module's
# docstring), so a freeform run in MOCK_MODE uses one generic, always-the-same mock response for
# them (FREEFORM_MOCKS below) rather than content tailored to what was typed. Agent 1 (parsing) and
# Agent 2 (duplicate check against the real seeded trial projects) still genuinely respond to the
# input — those are the two steps a novel submission actually exercises differently case to case.
# Set a real ANTHROPIC_API_KEY (see README's Mock mode section) and Agent 5/6 go live automatically,
# same as every other agent call in this codebase — nothing here special-cases that switch.
FREEFORM_MOCKS = {
    "agent5": {"margin_impact": "unclear", "citation": "New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch"},
    "agent6": {"verdict": "aligned", "citation": "AI-enabled operational tooling, supply chain digitization, customer-facing automation"},
}

FREEFORM_BODY_PLACEHOLDER = (
    "Objective: <the problem, one sentence>\n"
    "Proposed solution: <what you're proposing>\n\n"
    "Estimated business impact: $<amount>. Estimated CAPEX: $<amount>.\n"
    "Risk: <biggest known risk, or \"No significant risk identified at this stage\">\n\n"
    "Team: <names> — <department>, <region>."
)

def submit_freeform(from_field, subject, body):
    """Runs a real, typed submission through the actual pipeline. Returns the same
    status/"pending_gate2" vs "terminal" shape as run_scenario_to_gate2(), so the server route
    handles it identically to a named case."""
    raw_text = f"From: {from_field}\nSubject: {subject}\n\n{body}"
    parsed, _ms = parse_intake(raw_text)
    fields = parsed["parsed_fields"]

    conn = get_connection()
    _ensure_seeded(conn, "SUB-0001")  # real "existing" projects for Agent 2 to compare against

    submission_id = f"SUB-FREE-{int(time.time() * 1000) % 10_000_000}"
    project = Project(
        submission_id=submission_id,
        submitter_name=fields.get("submitter_name"),
        team_members=fields.get("team_members") or [],
        objective=fields.get("objective"),
        project_name=fields.get("project_name") or (subject.strip() or None),
        solution=fields.get("solution"),
        business_impact_usd=fields.get("business_impact_usd"),
        capex_usd=fields.get("capex_usd"),
        hypothesis_risk=fields.get("hypothesis_risk"),
    )

    trial_projects, _idx = load_trial_data()
    existing = [p for p in trial_projects if p.status in ("accepted", "in_progress", "completed")]
    trace = run_intake_to_gate2(conn, project, existing, FREEFORM_MOCKS)

    if trace.get("final_status") == "pending_gate2":
        gate2_file = f"gate2_{submission_id}.html"
        render_gate2(submission_id, project, trace)
        visualizer_id = _result_id(project, trace)
        v_path, v_steps = render_visualizer(visualizer_id, redirect_to=gate2_file)
        return {
            "status": "pending_gate2", "submission_id": submission_id, "visualizer_id": visualizer_id,
            "scenario_key": None, "project": project, "trace": trace,
            "paths": {"visualizer": v_path},
        }

    result_id = _result_id(project, trace)
    rendered = _render_all(result_id)
    return {"status": "terminal", "scenario_key": None, "trace": trace, "result_id": result_id,
            "parsed_fields": fields, "incomplete_fields": parsed.get("incomplete_fields", []), **rendered}
