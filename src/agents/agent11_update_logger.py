"""
Agent 11 — Update Logger. §2, §7.2.1.
No LLM — a structured diff, not a reasoning task, same "no LLM where none is needed" discipline as
Agents 3/4/7/9 (§16). Trigger: the project team (or a stakeholder) submits an ongoing status update
against an accepted/in_progress project. This agent's only job is to capture that update accurately
against the current baseline — it never judges whether the change is good or bad (that's Agent 12,
§7.2.2) and never writes to the `projects` row itself.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.repositories import insert_project_update

# Only fields that can legitimately change post-acceptance — the same five fields Agent 12's
# favorable/unfavorable check (§7.2.2) reasons over. Anything else submitted in an update payload
# (e.g. someone trying to change `project_name` or `region` via this path) is silently ignored here,
# not applied — those aren't "ongoing status" fields, changing them is a different kind of request
# this agent isn't scoped to handle.
UPDATABLE_FIELDS = ["expected_launch_date", "capex_usd", "risk_indicator", "schedule_status", "resource_indicator"]


def _get(project, field):
    return project.get(field) if isinstance(project, dict) else getattr(project, field, None)


def diff_update(project, submitted_fields: dict):
    """
    Pure function, no I/O — compares `submitted_fields` (only keys the submitter actually provided)
    against the project's current baseline. Returns (before_state, after_state, fields_changed).
    A field submitted with the *same* value as the baseline is not a change — it's excluded from
    fields_changed, same principle as any diff: only report what's actually different.
    """
    before_state, after_state, fields_changed = {}, {}, []
    for field in UPDATABLE_FIELDS:
        if field not in submitted_fields:
            continue
        old_val = _get(project, field)
        new_val = submitted_fields[field]
        if new_val == old_val:
            continue
        before_state[field] = old_val
        after_state[field] = new_val
        fields_changed.append(field)
    return before_state, after_state, fields_changed


def log_update(conn, project, submitted_fields: dict, submitted_by=None, note=None):
    """
    Full capture step: diff against baseline, then write unconditionally to `project_updates`
    (§3/§7.2.1) — even a no-op or a since-rejected change is worth having on record, same audit
    principle as `audit_log`. Returns the log entry dict (including the new row's id) for Agent 12
    to consume next; `evaluation`/`applied` are left unset here — that verdict isn't this agent's
    job to make (§7.2.2 is Phase 2, not built yet).
    """
    project_id = _get(project, "project_id") or _get(project, "submission_id")
    before_state, after_state, fields_changed = diff_update(project, submitted_fields)
    update_id = insert_project_update(
        conn, project_id, submitted_by, note, before_state, after_state, fields_changed,
        evaluation=None, applied=False,
    )
    return {
        "id": update_id,
        "project_id": project_id,
        "submitted_by": submitted_by,
        "note": note,
        "before_state": before_state,
        "after_state": after_state,
        "fields_changed": fields_changed,
    }
