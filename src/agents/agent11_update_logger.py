"""
Agent 11 — Update Logger. §2, §7.2.1.
No LLM — a structured diff, not a reasoning task, same "no LLM where none is needed" discipline as
Agents 3/4/7/9 (§16). Trigger: the project team (or a stakeholder) submits an ongoing status update
against an accepted/in_progress project. This agent's only job is to capture that update accurately
against the current baseline — it never judges whether the change is good or bad (that's Agent 12,
§7.2.2) and never writes to the `projects` row itself.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.repositories import insert_project_update
from src.agents.agent1_intake_parser import _parse_usd

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


# --- Real, typed update emails (§7.2.1, "make the list interactive" upversion) ---
# Case 8/9 (scripts/demo_engine.py) only ever ran two hardcoded CHANGE_DEMO_PAYLOADS against one
# fixed project. This is the genuine "any accepted/in_progress project, real typed text" entry point
# — same relationship Agent 1's parse_intake()/_deterministic_fallback_parse() has to the 7 named
# scenarios: a real extractor, not a stub, that never guesses a field that isn't actually stated in
# the text. Built against the compose box's own placeholder shape (see demo_engine.py's
# UPDATE_BODY_PLACEHOLDER) — a labeled-line format, not free prose, so extraction stays reliable
# without needing an LLM call for something this structured.
UPDATE_RISK_VALUES = {"green", "yellow", "red"}

# Shown in the compose box (scripts/demo_engine.py, scripts/demo_server.py) and matched exactly
# by parse_update_email() below — defined here, not duplicated in either UI-facing module, so the
# placeholder text and the parser it documents can never drift apart.
UPDATE_BODY_PLACEHOLDER = (
    "New launch date: <YYYY-MM-DD, or delete this line if unchanged>\n"
    "New CAPEX: $<amount, or delete this line if unchanged>\n"
    "Risk: <green/yellow/red, or delete this line if unchanged>\n"
    "Schedule: <green/yellow/red, or delete this line if unchanged>\n"
    "Resource: <green/yellow/red, or delete this line if unchanged>\n\n"
    "Note: <why this update, in your own words>"
)


def _extract_submitter_name(from_field: str) -> str:
    """'Grace Lim <grace.lim@company.com>' -> 'Grace Lim'. Falls back to the raw string if there's no
    '<...>' to strip — never fabricates a name that wasn't actually typed."""
    match = re.match(r"^\s*([^<]+?)\s*<", from_field or "")
    return match.group(1).strip() if match else (from_field or "").strip()


def parse_update_email(raw_text: str):
    """Extracts only the UPDATABLE_FIELDS that are actually present, labeled-line style (same
    convention as agent1_intake_parser.py's SCENARIO_EMAILS format, adapted to update fields instead
    of intake fields). Returns (fields: dict, note: str|None) — `fields` only ever contains keys that
    were genuinely found; a line that doesn't match the expected shape is simply absent, not guessed."""
    fields = {}

    date_match = re.search(r"(?:New\s+)?(?:expected\s+)?launch(?:\s+date)?:\s*(\d{4}-\d{2}-\d{2})", raw_text, re.I)
    if date_match:
        fields["expected_launch_date"] = date_match.group(1)

    capex_match = re.search(r"(?:New\s+)?CAPEX:\s*\$?([\d.,]+\s*(?:million)?)", raw_text, re.I)
    if capex_match:
        parsed = _parse_usd(capex_match.group(1))
        if parsed is not None:
            fields["capex_usd"] = parsed

    risk_match = re.search(r"\bRisk:\s*(green|yellow|red)\b", raw_text, re.I)
    if risk_match:
        fields["risk_indicator"] = risk_match.group(1).lower()

    schedule_match = re.search(r"\bSchedule:\s*(green|yellow|red)\b", raw_text, re.I)
    if schedule_match:
        fields["schedule_status"] = schedule_match.group(1).lower()

    resource_match = re.search(r"\bResource:\s*(green|yellow|red)\b", raw_text, re.I)
    if resource_match:
        fields["resource_indicator"] = resource_match.group(1).lower()

    note_match = re.search(r"\bNote:\s*(.+)", raw_text, re.I | re.S)
    note = note_match.group(1).strip() if note_match else None

    return fields, note
