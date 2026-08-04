"""
Agent 12 — Change Evaluator. §2, §7.2.2.
No LLM — a deterministic, auditable computation, same pattern as Agent 5's budget check (§5.2) and
Agent 10's success formula (§7): this is a governance decision, so it has to be a real computation
a PMO can verify line by line, not a model's opinion. Agent 12 is the only agent (besides Agent 7 at
acceptance) allowed to write to a live `projects` row, and only on the favorable path — the
unfavorable path only ever *proposes* via `change_requests`; Manual Gate 3 (§8.2 guardrail 3) still
has to say yes.
"""
import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.config import RISK_RANK
from src.db.repositories import (
    mark_project_update_resolved, apply_project_update, insert_change_request,
    write_audit_log, write_notification, get_change_request, resolve_change_request,
    get_project_by_ref, update_status,
)
from src.orchestration.state_machine import transition
from src.notifications.templates import change_auto_applied, change_authorized, change_declined, change_cancelled

# The three axes the requested rule actually names — "earlier timeline, lesser expenses, reduced
# risk." schedule_status/resource_indicator are also in Agent 11's UPDATABLE_FIELDS (§7.2.1) but are
# tracking colors, not governance decisions on their own — a change touching only those two has
# nothing here to be unfavorable about, so it auto-applies without needing an "improvement" (§7.2.5:
# Agent 12 never re-derives risk/schedule/resource values, it only reads what was reported).
GOVERNANCE_AXES = {
    "expected_launch_date": "timeline",
    "capex_usd": "cost",
    "risk_indicator": "risk",
}


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _direction(field, old_val, new_val):
    """Returns 'improved' | 'same' | 'regressed', or None if the axis can't be evaluated (missing/
    unparseable baseline) — an axis we can't read is excluded from the decision, never guessed."""
    if old_val is None or new_val is None:
        return None
    if field == "expected_launch_date":
        old_d, new_d = _parse_date(old_val), _parse_date(new_val)
        if old_d is None or new_d is None:
            return None
        return "improved" if new_d < old_d else ("regressed" if new_d > old_d else "same")
    if field == "capex_usd":
        return "improved" if new_val < old_val else ("regressed" if new_val > old_val else "same")
    if field == "risk_indicator":
        if new_val not in RISK_RANK or old_val not in RISK_RANK:
            return None
        return "improved" if RISK_RANK[new_val] < RISK_RANK[old_val] else (
            "regressed" if RISK_RANK[new_val] > RISK_RANK[old_val] else "same")
    return None


def evaluate(before_state: dict, after_state: dict):
    """
    Pure function, no I/O. Rule: favorable iff no regression on any governance axis that was
    actually changed, AND at least one of those axes is a strict improvement.
    [ASSUMPTION, flagged in TECH-SPEC.md §7.2.2]: "earlier timeline, lesser expenses, or reduced
    risk" reads as "any one is good news," but that would let risk climb unchecked as long as CAPEX
    ticked down. This is the safer AND-with-no-regression reading — swap to OR if PMO wants any
    single improvement to be sufficient on its own.
    """
    axis_results = {}
    for field, axis_name in GOVERNANCE_AXES.items():
        if field not in after_state:
            continue
        direction = _direction(field, before_state.get(field), after_state.get(field))
        if direction is None:
            continue
        axis_results[axis_name] = {
            "field": field, "before": before_state.get(field), "after": after_state.get(field),
            "direction": direction,
        }

    if not axis_results:
        return {"evaluation": "favorable", "axis_results": {},
                "reason": "no governance-relevant field (timeline/cost/risk) changed"}

    regressed = [a for a, r in axis_results.items() if r["direction"] == "regressed"]
    improved = [a for a, r in axis_results.items() if r["direction"] == "improved"]

    if regressed:
        return {"evaluation": "needs_authorization", "axis_results": axis_results,
                "reason": f"regressed on: {', '.join(regressed)}"}
    if improved:
        return {"evaluation": "favorable", "axis_results": axis_results,
                "reason": f"improved on: {', '.join(improved)}, no regression elsewhere"}
    # every touched axis is exactly unchanged in value (rare — diff_update already excludes no-op
    # submissions, but e.g. a date reformatted to the same day could land here) — no real
    # improvement to justify auto-applying, so this is conservatively routed to PMO rather than
    # silently applied.
    return {"evaluation": "needs_authorization", "axis_results": axis_results,
            "reason": "no strict improvement on any changed governance axis"}


def process_update(conn, update_entry: dict, project_name: str, requested_by=None):
    """
    Orchestrates the full Agent 12 step for one Agent-11-logged update: evaluate, then either apply
    (favorable) or open a real Manual Gate 3 (needs_authorization). `update_entry` is the dict
    returned by agent11_update_logger.log_update(). Returns the evaluation result plus what Agent 12
    actually did (`applied` or `change_request_id`).
    """
    project_id = update_entry["project_id"]
    before_state, after_state = update_entry["before_state"], update_entry["after_state"]
    verdict = evaluate(before_state, after_state)

    if verdict["evaluation"] == "favorable":
        apply_project_update(conn, project_id, after_state)
        mark_project_update_resolved(conn, update_entry["id"], "favorable", applied=True)
        write_audit_log(conn, project_id, "agent12_change_evaluator", "auto_apply",
                         {"fields_changed": update_entry["fields_changed"], **verdict}, 0)
        notif = change_auto_applied(project_name, project_id, before_state, after_state, verdict["reason"])
        write_notification(conn, project_id, "PMO Team", "email", notif["subject"], notif["body"],
                            trigger_agent="agent12_change_evaluator")
        return {**verdict, "applied": True, "change_request_id": None,
                "notification": {**notif, "recipient": "PMO Team", "channel": "email"}}

    change_request_id = insert_change_request(
        conn, update_entry["id"], project_id, requested_by or update_entry.get("submitted_by"),
        verdict["reason"],
    )
    mark_project_update_resolved(conn, update_entry["id"], "needs_authorization", applied=False)
    write_audit_log(conn, project_id, "agent12_change_evaluator", "escalate_to_gate3",
                     {"fields_changed": update_entry["fields_changed"], "change_request_id": change_request_id, **verdict}, 0)
    return {**verdict, "applied": False, "change_request_id": change_request_id}


def resolve_gate3(conn, change_request_id, decision, project_name, pmo_comment="", resolved_by="PMO"):
    """
    §7.2.2's Gate 3 resolution — the human decision Agent 12 was waiting on. `decision` is
    'accept'/'reject'/'cancel'. On accept, applies the exact after_state Agent 11 originally captured
    (Agent 12 never re-derives it) and marks the underlying project_updates row applied. On cancel,
    the proposed update itself is NOT applied (same as reject — the specific field changes never take
    effect), but the project's own status transitions to 'cancelled' — a real, distinct governance
    outcome (§ schemas.py's Status.CANCELLED docstring) for when the update PMO was reviewing reveals
    the project is slipping badly enough that continuing isn't worth it, not just this one change.
    Same hard-not-bypassable-by-an-agent rule as Gates 1/2 (§8.2 guardrail 3) — this function only
    runs once a real PMO decision has been made; nothing calls it automatically.
    """
    if decision not in ("accept", "reject", "cancel"):
        raise ValueError(f"decision must be accept, reject, or cancel (got {decision!r})")
    cr = get_change_request(conn, change_request_id)
    if cr is None:
        raise ValueError(f"Unknown change_request_id: {change_request_id}")
    if cr["status"] != "pending":
        raise ValueError(f"change_request {change_request_id} already resolved (status={cr['status']})")

    from src.db.repositories import get_project_updates
    update_row = next((u for u in get_project_updates(conn, cr["original_project_id"])
                        if u["id"] == cr["project_update_id"]), None)
    project_id = cr["original_project_id"]

    if decision == "accept":
        after_state = update_row["after_state"] if update_row else {}
        apply_project_update(conn, project_id, after_state)
        if update_row:
            mark_project_update_resolved(conn, update_row["id"], "favorable_by_pmo", applied=True)
        resolve_change_request(conn, change_request_id, "approved", pmo_comment, resolved_by)
        write_audit_log(conn, project_id, "agent12_change_evaluator", "gate3_approved",
                         {"change_request_id": change_request_id, "after_state": after_state}, 0)
        notif = change_authorized(project_name, project_id, after_state, pmo_comment)
        status = "approved"
    elif decision == "reject":
        resolve_change_request(conn, change_request_id, "rejected", pmo_comment, resolved_by)
        write_audit_log(conn, project_id, "agent12_change_evaluator", "gate3_rejected",
                         {"change_request_id": change_request_id, "reason": pmo_comment}, 0)
        notif = change_declined(project_name, project_id, cr["reason"], pmo_comment)
        status = "rejected"
    else:  # cancel
        # The proposed update itself never applies (same non-effect as reject) — what's different is
        # the PROJECT's own status, which moves to cancelled. get_project_by_ref/update_status work
        # off submission_id, not project_id (see complete_project()'s identical pattern in
        # scripts/demo_engine.py), so resolve the real row first rather than assuming they're the
        # same string.
        row = get_project_by_ref(conn, project_id)
        if row is None:
            raise ValueError(f"Unknown project '{project_id}' — cannot cancel.")
        new_status = transition(row["status"], "cancelled")
        update_status(conn, row["submission_id"], new_status)
        apply_project_update(conn, project_id, {"rejection_reason": f"Cancelled by PMO at Gate 3 — {cr['reason']}"})
        resolve_change_request(conn, change_request_id, "rejected", pmo_comment, resolved_by)
        write_audit_log(conn, project_id, "agent12_change_evaluator", "gate3_cancelled",
                         {"change_request_id": change_request_id, "reason": cr["reason"]}, 0)
        notif = change_cancelled(project_name, project_id, cr["reason"], pmo_comment)
        status = "cancelled"

    recipient = cr["requested_by"] or "Project team"
    write_notification(conn, project_id, recipient, "email",
                        notif["subject"], notif["body"], trigger_agent="agent12_change_evaluator")
    return {"status": status, "project_id": project_id,
            "notification": {**notif, "recipient": recipient, "channel": "email"}}
