"""
Pipeline — dispatch/sequencing between agents (§15). Wires Agents 1,2,3/4,5,6,7,8,9,10 plus the
state machine and audit log into one runnable, fully-traced flow per submission. This is what the
demo composer (§12.1, Phase 4.4) drives, and what the Live Execution Visualizer (§9.1) replays.

Split into two halves at Manual Gate 2 (§2/§8.2 guardrail 3 — gates cannot be bypassed by any
agent): run_intake_to_gate2() does everything up through Agent 6's analysis and then stops;
resume_after_gate2() only runs once an actual PMO decision (accept/reject) has been made.
run_submission() is a convenience wrapper that runs both halves back to back for callers that
don't need a real pause (the CLI demo script, the test suite) — the in-browser composer
(scripts/demo_server.py) calls the two halves separately so Gate 2 is a genuine stop, not a
default that's silently applied.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.agents.agent1_intake_parser import REQUIRED_FIELDS
from src.agents.agent2_duplicate_checker import check_duplicate
from src.agents.agent5_business_impact_analyzer import analyze_business_impact
from src.agents.agent6_knowledge_crosschecker import cross_check
from src.agents.agent7_acceptance_handler import issue_project_id
from src.agents.agent8_rejection_feedback_composer import compose_rejection
from src.notifications.templates import submission_received, duplicate_rejection, pmo_new_submission_alert, acceptance, under_monitoring, rejection_feedback
from src.db.repositories import insert_project, update_status, write_audit_log, write_notification
from src.orchestration.state_machine import transition, accept_project
from src.shared.schemas import Status
from src.shared.config import REUSE_SIMILARITY_THRESHOLD
from src.knowledge.opl_loader import load_opl, extract_section


def _log_step(conn, project, trace, agent, action, payload, duration_ms=0):
    trace["steps"].append({"agent": agent, "action": action, "duration_ms": duration_ms})
    write_audit_log(conn, project.project_id or project.submission_id, agent, action, payload, duration_ms)

def _send(conn, project, trace, notif, trigger_agent, recipient=None):
    # Persist every notification, not just print it — this is what dashboard/render_notifications.py
    # (and the visualizer's "Notification sent" panel) read. Previously notifications only lived in
    # the returned trace dict and got printed to the terminal by scripts/run_demo.py, so nothing was
    # ever visible in the dashboard itself. trigger_agent records WHICH step caused this notification
    # so the dashboard can show "at which phase" it went out, instead of just a bare list of emails.
    # `recipient` defaults to the requester (most notifications are requester-facing per §11); pass
    # it explicitly for internal, PMO-facing ones (e.g. Agent 4's "new submission" alert).
    trace["notifications"].append(notif)
    recipient = recipient or project.submitter_name or "Stakeholder"
    write_notification(conn, project.project_id or project.submission_id, recipient, "email",
                        notif["subject"], notif["body"], trigger_agent=trigger_agent)


def run_intake_to_gate2(conn, project, existing_projects, mocks: dict, gate1_decision="proceed"):
    """
    Agents 1, 2, (3 if duplicate), Gate 1, 4, 5, 6. Stops right before Gate 2's accept/reject
    decision. Returns a trace dict — either a terminal outcome (rejected at intake/duplicate/Gate 1,
    or inconclusive -> back to pmo_review) with final_status already set, or
    final_status == "pending_gate2" with agent5/agent6 findings attached so a real PMO decision can
    be made against them.
    """
    trace = {"submission_id": project.submission_id, "steps": [], "notifications": []}

    # Immediate acknowledgment — fires unconditionally, before any validation happens, so the
    # originator hears something back the instant their submission lands, for every case study
    # (§11) including ones that end up rejected downstream (incomplete, duplicate, misaligned).
    _log_step(conn, project, trace, "agent1_intake_parser", "acknowledge_receipt", {})
    _send(conn, project, trace, submission_received(project.project_name or "your submission"), "agent1_intake_parser")

    # Agent 1 — intake validation. Trial-data entries arrive already structured (not raw email
    # text), but Agent 1's required-field check still applies to them and still gets logged —
    # this is the entry point of every trace, not something skipped once parsing has happened.
    missing = [f for f in REQUIRED_FIELDS if not getattr(project, f, None)]
    _log_step(conn, project, trace, "agent1_intake_parser", "validate", {"missing_fields": missing})
    if missing:
        insert_project(conn, project)
        trace["final_status"] = "rejected"
        trace["rejection_reason"] = f"Incomplete information — missing {', '.join(missing)}"
        _send(conn, project, trace, rejection_feedback(project.project_name or "your submission", "Incomplete information provided at intake"), "agent1_intake_parser")
        return trace

    # Agent 2 — duplicate check
    dup_out, dup_ms = check_duplicate(project, existing_projects, mock_response=mocks.get("agent2_adjudication"))
    _log_step(conn, project, trace, "agent2_duplicate_checker", "check", dup_out, dup_ms)

    if dup_out["verdict"] == "duplicate":
        insert_project(conn, project)
        update_status(conn, project.submission_id, transition(Status.DRAFT.value, Status.REJECTED.value))
        notif = duplicate_rejection(project.project_name, dup_out["match"], "the original submitter")
        _log_step(conn, project, trace, "agent3_duplicate_rejection_notifier", "notify", notif)
        _send(conn, project, trace, notif, "agent3_duplicate_rejection_notifier")
        trace["final_status"] = "rejected"
        trace["rejection_reason"] = f"Duplicate of {dup_out['match']}"
        return trace

    # Gate 1
    insert_project(conn, project)
    if gate1_decision == "reject":
        update_status(conn, project.submission_id, transition(Status.DRAFT.value, Status.REJECTED.value))
        trace["final_status"] = "rejected"
        return trace

    update_status(conn, project.submission_id, transition(Status.DRAFT.value, Status.PMO_REVIEW.value))
    update_status(conn, project.submission_id, transition(Status.PMO_REVIEW.value, Status.ANALYSIS.value))

    # Agent 4 — PMO router (§2 row 4: "Notify PMO inbox; awaits manual gate 1"). Internal-only: this
    # tells PMO a new application has arrived, nothing more — no premature "your project is
    # registered under ID X" to the requester before Agent 5/6 have even run (that would be
    # announcing a decision that hasn't been made yet). The requester already has Agent 1's
    # "received, under review" ack and hears nothing else until a real Gate 2 decision resolves —
    # acceptance (with the actual assigned project ID) via Agent 7, or the rejection reason via
    # Agent 8.
    pmo_alert = pmo_new_submission_alert(
        project.project_name, project.submitter_name or "Unknown submitter",
        project.project_id or project.submission_id,
    )
    _log_step(conn, project, trace, "agent4_pmo_router", "notify_pmo", pmo_alert)
    _send(conn, project, trace, pmo_alert, "agent4_pmo_router", recipient="PMO Team")

    # §7.2.4 — a not_duplicate match that's still reasonably similar, and has a published OPL
    # (§7.2.3), is worth surfacing to Agent 5 as a "here's what worked on something similar before"
    # note. Deterministic lookup, not an LLM judgment call — the excerpt itself is a real, already-
    # grounded quote pulled straight from that project's OPL file.
    similar_past_project = None
    if dup_out.get("match") and dup_out.get("similarity", 0) >= REUSE_SIMILARITY_THRESHOLD:
        matched_id = dup_out["match"]
        matched_project = next(
            (p for p in existing_projects if (p.project_id or p.submission_id) == matched_id), None
        )
        if matched_project:
            excerpt = extract_section(load_opl(matched_project.project_id), "What worked / what to reuse")
            if excerpt:
                similar_past_project = {
                    "project_id": matched_project.project_id or matched_project.submission_id,
                    "project_name": matched_project.project_name,
                    "similarity": dup_out["similarity"],
                    "excerpt": excerpt,
                }

    # Agent 5 + 6
    a5_out, a5_ms = analyze_business_impact(
        project, mock_response=mocks.get("agent5"), conn=conn, similar_past_project=similar_past_project
    )
    _log_step(conn, project, trace, "agent5_business_impact", "analyze", a5_out, a5_ms)
    a6_out, a6_ms = cross_check(project, mock_response=mocks.get("agent6"))
    _log_step(conn, project, trace, "agent6_knowledge_crosscheck", "crosscheck", a6_out, a6_ms)
    trace["agent5"] = a5_out
    trace["agent6"] = a6_out

    if a6_out["verdict"] == "inconclusive":
        update_status(conn, project.submission_id, transition(Status.ANALYSIS.value, Status.PMO_REVIEW.value))
        trace["final_status"] = "pmo_review (under review)"
        return trace

    trace["final_status"] = "pending_gate2"
    return trace


def default_gate2_rejection_reason(a6_out):
    """The reason Agent 8 would propose on its own, before any PMO edits it. Shared between
    resume_after_gate2() (the actual fallback if no override is given) and the Gate 2 review page
    (dashboard/render_gate2.py, which prefills its reason field with exactly this) so the two never
    drift apart."""
    return "Not aligned with strategic focus regions or product areas" if a6_out["verdict"] == "misaligned" else "PMO rejected at Gate 2"


def resume_after_gate2(conn, project, trace, gate2_decision, override_reason=None, pmo_comment="",
                        gate2_batch_id=None, exception_reason=None):
    """
    Completes the flow once an actual PMO decision has been made at Manual Gate 2. `trace` must be
    the dict returned by run_intake_to_gate2() with final_status == "pending_gate2" (it carries
    agent6's verdict, which this step is not allowed to re-derive or second-guess — the human's
    decision is final per §8.2 guardrail 3).

    On reject, `override_reason` lets the PMO replace Agent 8's proposed reason outright (left None
    or blank, the proposed reason is used as-is); `pmo_comment` lets them add to it without
    replacing it. Both flow straight into the actual rejection notification sent to the requester.

    On accept, `pmo_comment` is the same idea in the other direction — an optional note (praise, a
    watch-out, a condition to track post-acceptance) appended to the acceptance notification and
    logged on Agent 7's audit_log entry. Never required; a plain accept works exactly as before.

    `gate2_batch_id`/`exception_reason` (§5.3) — which weekly sitting this was decided in, if any,
    and why it was decided outside one (policy fast-track or a logged PMO override), stamped onto
    the resolution's own audit_log entry rather than a separate decision-tracking table.
    """
    a6_out = trace["agent6"]
    batch_meta = {"gate2_batch_id": gate2_batch_id, "exception_reason": exception_reason}

    if gate2_decision == "accept":
        new_status = accept_project(conn, project.submission_id, "accept")
        row = conn.execute("SELECT project_id FROM projects WHERE submission_id = ?", (project.submission_id,)).fetchone()
        # Idempotent, same rule as before: reuse an existing project_id rather than issuing a new
        # one, so the audit trail (and this trace) stays on one ID end to end.
        project_id = row["project_id"] if row and row["project_id"] else issue_project_id()
        conn.execute("UPDATE projects SET project_id = ? WHERE submission_id = ?", (project_id, project.submission_id))
        conn.commit()
        project.project_id = project_id
        pmo_comment = (pmo_comment or "").strip()
        notif = acceptance(project.project_name, project_id, pmo_comment=pmo_comment)
        _log_step(conn, project, trace, "agent7_acceptance_handler", "accept",
                   {"project_id": project_id, "pmo_comment": pmo_comment, **batch_meta})
        _send(conn, project, trace, notif, "agent7_acceptance_handler")
        trace["final_status"] = new_status
        trace["project_id"] = project_id

        # Agent 9 — dashboard service. Continuous/always-on in the full system (§9), not a
        # reasoning step, but a newly-accepted project's first publish to the dashboard is a real
        # event worth a place in the trace — otherwise Agent 9 never appears anywhere at all.
        _log_step(conn, project, trace, "agent9_dashboard_service", "publish", {"project_id": project_id})

        # Agent 10 — success predictor (§7). A project accepted moments ago has zero tracking
        # history, so it starts "Under monitoring" rather than an immediate (meaningless) score —
        # the same age gate (SUCCESS_PREDICTOR_MIN_AGE_DAYS) the topline dashboard applies across
        # the whole portfolio, via agent10_success_predictor.predict_or_monitor().
        conn.execute("UPDATE projects SET success_score = NULL WHERE submission_id = ?", (project.submission_id,))
        conn.commit()
        _log_step(conn, project, trace, "agent10_success_predictor", "monitor", {"status": "under_monitoring"})
        trace["success_score"] = None
        trace["success_status"] = "under_monitoring"
        _send(conn, project, trace, under_monitoring(project.project_name, project_id), "agent10_success_predictor")
    else:
        update_status(conn, project.submission_id, transition(Status.ANALYSIS.value, Status.REJECTED.value))
        reason = (override_reason or "").strip() or default_gate2_rejection_reason(a6_out)
        rej, rej_ms = compose_rejection(project.project_name, reason, pmo_comment=pmo_comment)
        _log_step(conn, project, trace, "agent8_rejection_feedback_composer", "compose", {**rej, **batch_meta}, rej_ms)
        _send(conn, project, trace, rej, "agent8_rejection_feedback_composer")
        trace["final_status"] = "rejected"
        trace["rejection_reason"] = reason

    return trace


def run_submission(conn, project, existing_projects, mocks: dict, gate1_decision="proceed", gate2_decision="accept"):
    """
    Convenience wrapper for callers that don't need Gate 2 to be a real pause (CLI demo script,
    tests): runs intake through Gate 2 and, if it lands on "pending_gate2", immediately resolves it
    using `gate2_decision` as if a PMO had already decided. The in-browser composer
    (scripts/demo_server.py) does NOT use this — it calls run_intake_to_gate2() and
    resume_after_gate2() separately so Gate 2 is an actual stop with a real button click in between.
    """
    trace = run_intake_to_gate2(conn, project, existing_projects, mocks, gate1_decision)
    if trace.get("final_status") == "pending_gate2":
        trace = resume_after_gate2(conn, project, trace, gate2_decision)
    return trace
