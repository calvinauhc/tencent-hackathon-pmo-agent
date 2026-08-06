"""Typed queries per table — §15 db/repositories."""
import json, time
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.schemas import Project

def insert_project(conn, p: Project):
    conn.execute(
        """INSERT OR REPLACE INTO projects
        (submission_id, project_id, submitter_name, team_members, objective, project_name, solution,
         business_impact_usd, expected_launch_date, hypothesis_risk, risk_category, capex_usd, capex_funded_pct, status,
         region, business_unit, risk_indicator, schedule_status, resource_indicator, help_needed, rejection_reason,
         success_score, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (p.submission_id, p.project_id, p.submitter_name, json.dumps(p.team_members), p.objective,
         p.project_name, p.solution, p.business_impact_usd, p.expected_launch_date, p.hypothesis_risk, p.risk_category,
         p.capex_usd, p.capex_funded_pct, p.status, p.region, p.business_unit, p.risk_indicator,
         p.schedule_status, p.resource_indicator, p.help_needed, p.rejection_reason, p.success_score, p.created_at, p.updated_at)
    )
    conn.commit()

def get_project(conn, submission_id):
    row = conn.execute("SELECT * FROM projects WHERE submission_id = ?", (submission_id,)).fetchone()
    return dict(row) if row else None

def get_project_by_ref(conn, ref):
    """§7.2 — post-acceptance callers (Agent 11/12, the Gate 3 page) generally only have a project's
    real `project_id` (e.g. PRJ-2026-0791) to work with, not its original `submission_id` — unlike
    get_project() above, which is keyed to submission_id for the pre-acceptance pipeline. Tries
    project_id first (the common post-acceptance case), then falls back to submission_id."""
    row = conn.execute("SELECT * FROM projects WHERE project_id = ?", (ref,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM projects WHERE submission_id = ?", (ref,)).fetchone()
    return dict(row) if row else None

def update_status(conn, submission_id, new_status):
    # `updated_at` was previously left untouched here — every project's timestamp stayed whatever
    # the synthetic trial-data seed authored it as, so the topline dashboard's "most recent 20"
    # ordering (§9) reflected fixture data, not real pipeline activity. A project a PMO just ran
    # live through Gate 1/2 could rank behind dozens of untouched seed rows and never show up on
    # their own dashboard. Bump it to now on every real status transition, same as any live system.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE projects SET status = ?, updated_at = ? WHERE submission_id = ?", (new_status, now, submission_id))
    conn.commit()

def write_audit_log(conn, project_id, agent, action, payload, duration_ms):
    conn.execute(
        "INSERT INTO audit_log (project_id, agent, action, payload, duration_ms, created_at) VALUES (?,?,?,?,?,?)",
        (project_id, agent, action, json.dumps(payload), duration_ms, str(time.time()))
    )
    conn.commit()

def get_audit_log(conn, project_id):
    rows = conn.execute("SELECT * FROM audit_log WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [dict(r) for r in rows]

def write_comment(conn, project_id, author, role, body, is_flagged_concern=False, linked_gate=None):
    conn.execute(
        """INSERT INTO project_comments (project_id, author, role, body, is_flagged_concern, linked_gate, created_at)
        VALUES (?,?,?,?,?,?,?)""",
        (project_id, author, role, body, int(is_flagged_concern), linked_gate, str(time.time()))
    )
    conn.commit()

def get_comments(conn, project_id):
    rows = conn.execute("SELECT * FROM project_comments WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [dict(r) for r in rows]

def write_notification(conn, project_id, recipient, channel, subject, body, trigger_agent=None):
    conn.execute(
        "INSERT INTO notifications (project_id, recipient, channel, subject, body, sent_at, trigger_agent) VALUES (?,?,?,?,?,?,?)",
        (project_id, recipient, channel, subject, body, str(time.time()), trigger_agent)
    )
    conn.commit()

def get_notifications(conn, project_id):
    rows = conn.execute("SELECT * FROM notifications WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [dict(r) for r in rows]

def get_recent_notifications(conn, limit=100):
    rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_recent_audit_log(conn, limit=200):
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_recent_comments(conn, limit=100):
    rows = conn.execute("SELECT * FROM project_comments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def insert_project_update(conn, project_id, submitted_by, note, before_state, after_state,
                           fields_changed, evaluation=None, applied=False):
    """§7.2.1 Agent 11's capture step — append-only, unconditional. `evaluation`/`applied` are
    usually filled in by the same call once Agent 12 has judged it (Phase 1 doesn't build Agent 12
    yet, so both stay None/False for now); the row always gets written regardless of what Agent 12
    later decides — a rejected or contested update is still worth having on record."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """INSERT INTO project_updates
        (project_id, submitted_by, note, before_state, after_state, fields_changed, evaluation, applied, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (project_id, submitted_by, note, json.dumps(before_state), json.dumps(after_state),
         json.dumps(fields_changed), evaluation, int(bool(applied)), now)
    )
    conn.commit()
    return cur.lastrowid

def get_project_updates(conn, project_id):
    rows = conn.execute(
        "SELECT * FROM project_updates WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["before_state"] = json.loads(d["before_state"]) if d["before_state"] else {}
        d["after_state"] = json.loads(d["after_state"]) if d["after_state"] else {}
        d["fields_changed"] = json.loads(d["fields_changed"]) if d["fields_changed"] else []
        out.append(d)
    return out

def mark_project_update_resolved(conn, update_id, evaluation, applied):
    """§7.2.2 — Agent 12 stamps its verdict back onto the project_updates row Agent 11 wrote, once
    a decision (auto-apply, or a Gate 3 resolution) actually exists. The row itself is never edited
    otherwise — this is the one and only follow-up write it ever gets."""
    conn.execute(
        "UPDATE project_updates SET evaluation = ?, applied = ? WHERE id = ?",
        (evaluation, int(bool(applied)), update_id)
    )
    conn.commit()

def apply_project_update(conn, project_id, after_state: dict):
    """§7.2.2 — the only place outside Agent 7 (acceptance) that writes to a live `projects` row
    post-acceptance. `after_state` only ever contains keys from agent11's UPDATABLE_FIELDS allowlist
    (closed set, not arbitrary user input), so building the column list dynamically here is safe."""
    if not after_state:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cols = list(after_state.keys())
    set_clause = ", ".join(f"{c} = ?" for c in cols) + ", updated_at = ?"
    values = [after_state[c] for c in cols] + [now, project_id]
    conn.execute(f"UPDATE projects SET {set_clause} WHERE project_id = ?", values)
    conn.commit()

def insert_change_request(conn, project_update_id, original_project_id, requested_by, reason):
    """§7.2.2 — written only for updates Agent 12 evaluated 'needs_authorization'. This is what
    makes Manual Gate 3 real: a `pending` row here is exactly what the Gate 3 review page (§9.3.4-
    style) reads and resolves."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """INSERT INTO change_requests
        (project_update_id, original_project_id, requested_by, reason, status, created_at)
        VALUES (?,?,?,?,?,?)""",
        (project_update_id, original_project_id, requested_by, reason, "pending", now)
    )
    conn.commit()
    return cur.lastrowid

def get_change_request(conn, change_request_id):
    row = conn.execute("SELECT * FROM change_requests WHERE id = ?", (change_request_id,)).fetchone()
    return dict(row) if row else None

def get_pending_change_requests(conn):
    rows = conn.execute("SELECT * FROM change_requests WHERE status = 'pending' ORDER BY id").fetchall()
    return [dict(r) for r in rows]

def resolve_change_request(conn, change_request_id, status, pmo_comment="", resolved_by="PMO", new_project_id=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """UPDATE change_requests SET status = ?, pmo_comment = ?, resolved_by = ?, resolved_at = ?,
        new_project_id = COALESCE(?, new_project_id) WHERE id = ?""",
        (status, pmo_comment, resolved_by, now, new_project_id, change_request_id)
    )
    conn.commit()

def insert_kb_document(conn, doc_type, chunk_text, project_id=None, reviewed_by=None, version=1):
    """§7.2.3 — Agent 13's publish step (doc_type='opl'), same table playbook/pvp/political/
    regulatory would use if this demo actually chunked/embedded them (§5 CAG note — it doesn't;
    they're read straight from data/*.md via docs_loader.py). Superseding an existing OPL for the
    same project marks the old row inactive rather than deleting it, same audit-trail principle as
    every other append-only table here."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if project_id:
        conn.execute(
            "UPDATE kb_documents SET is_active = 0 WHERE doc_type = ? AND project_id = ? AND is_active = 1",
            (doc_type, project_id)
        )
    cur = conn.execute(
        """INSERT INTO kb_documents (doc_type, project_id, chunk_text, version, reviewed_by, last_reviewed_at, is_active)
        VALUES (?,?,?,?,?,?,1)""",
        (doc_type, project_id, chunk_text, version, reviewed_by, now)
    )
    conn.commit()
    return cur.lastrowid

def get_opl_kb_row(conn, project_id):
    row = conn.execute(
        "SELECT * FROM kb_documents WHERE doc_type = 'opl' AND project_id = ? AND is_active = 1",
        (project_id,)
    ).fetchone()
    return dict(row) if row else None

def get_change_requests_for_project(conn, project_id):
    rows = conn.execute(
        "SELECT * FROM change_requests WHERE original_project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    return [dict(r) for r in rows]

def open_gate2_batch(conn, opened_by="PMO"):
    """§5.3 — starts a weekly sitting. Only one batch is ever open at a time (get_open_gate2_batch
    below always looks for the most recent unclosed row); opening a new one while another is still
    open is the caller's responsibility to avoid, same as any other demo-trigger guard here."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute("INSERT INTO gate2_batches (opened_at, opened_by) VALUES (?,?)", (now, opened_by))
    conn.commit()
    return cur.lastrowid

def close_gate2_batch(conn, batch_id):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE gate2_batches SET closed_at = ? WHERE id = ?", (now, batch_id))
    conn.commit()

def get_open_gate2_batch(conn):
    row = conn.execute("SELECT * FROM gate2_batches WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None

def get_gate2_queue(conn):
    """§5.3 — the queue *is* every project sitting at status='analysis' (Agent 6 finished, Gate 2
    not yet decided); no separate queue table needed. Ordered oldest-first so a batch review works
    through the longest-waiting projects first."""
    rows = conn.execute("SELECT * FROM projects WHERE status = 'analysis' ORDER BY updated_at").fetchall()
    return [dict(r) for r in rows]

def get_active_projects(conn):
    """Every accepted/in_progress project — real, live DB state. Was inlined separately in
    scripts/demo_engine.py's get_updatable_projects() (the "send a project update" panel's source
    list) and now also backs dashboard/render_active_projects.py's live risk/schedule/resource
    view (§14 follow-up — the topline dashboard used to be the only place this was visible; when
    it was removed, nothing replaced it, so an applied schedule/risk/resource change had no live
    view to confirm it took effect). draft/pmo_review/analysis rows haven't been accepted yet, and
    completed/cancelled/rejected ones are terminal (schemas.py's ALLOWED_TRANSITIONS) — same filter
    render_topline.py used to apply directly. Ordered newest-updated-first so a change a PMO just
    applied surfaces at the top, not buried under untouched seed rows."""
    rows = conn.execute(
        "SELECT * FROM projects WHERE status IN ('accepted', 'in_progress') ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]

def get_latest_agent_payload(conn, project_id, agent):
    """§5.3 — reconstructs a queued project's Agent 5/6 findings from audit_log on demand, for
    rendering its Gate 2 page when a PMO pulls it out of the queue to review (rather than keeping
    every queued project's trace sitting in server memory the whole time it waits)."""
    row = conn.execute(
        "SELECT payload FROM audit_log WHERE project_id = ? AND agent = ? ORDER BY id DESC LIMIT 1",
        (project_id, agent)
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["payload"])
    except (TypeError, ValueError):
        return None

def get_regional_committed_capex(conn, region, exclude_submission_id=None):
    """§5 playbook.md "Regional CAPEX Budgets" — sum of CAPEX already committed (accepted, in
    progress, or completed) for a region, used by Agent 5's deterministic budget check. Excludes
    the submission being evaluated itself, in case it was already inserted (analysis-stage rows
    never carry a committed status, but excluding by ID keeps this correct regardless)."""
    if not region:
        return 0.0
    row = conn.execute(
        """SELECT COALESCE(SUM(capex_usd), 0) AS total FROM projects
        WHERE region = ? AND status IN ('accepted', 'in_progress', 'completed')
        AND submission_id != ?""",
        (region, exclude_submission_id or ""),
    ).fetchone()
    return float(row["total"]) if row else 0.0
