"""
DB client — §3 schema, SQLite for this build (per §16 note: swap to Postgres by editing
only this file when porting to CodeBuddy; schema shape stays identical).
"""
import sqlite3, json, os

# Runtime DB lives outside the project folder — this repo directory is mounted over a
# network filesystem that doesn't support SQLite's file locking (confirmed: "disk I/O error"
# on write). A .db file is a build artifact anyway, not source; this has zero effect on the
# CodeBuddy port, which targets a real Postgres instance (§16), not this local file.
DB_PATH = os.environ.get("PMO_MVP_DB_PATH", "/tmp/pmo_mvp.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    submission_id TEXT PRIMARY KEY,
    project_id TEXT UNIQUE,
    submitter_name TEXT, team_members TEXT, objective TEXT, project_name TEXT, solution TEXT,
    business_impact_usd REAL, expected_launch_date TEXT, hypothesis_risk TEXT, risk_category TEXT,
    capex_usd REAL, capex_funded_pct REAL, status TEXT,
    region TEXT, business_unit TEXT, risk_indicator TEXT, schedule_status TEXT, resource_indicator TEXT,
    help_needed TEXT, rejection_reason TEXT, success_score REAL,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS project_updates (
    -- §7.2.1 Agent 11's raw capture log — every ongoing status update, before Agent 12 (§7.2.2)
    -- has judged it. Append-only; never edited or deleted, same audit principle as audit_log.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT, submitted_by TEXT, note TEXT,
    before_state TEXT,   -- JSON snapshot of the fields being changed, prior value
    after_state TEXT,    -- JSON, proposed new value for the same fields
    fields_changed TEXT, -- JSON list, e.g. ["expected_launch_date", "capex_usd"]
    evaluation TEXT,     -- 'favorable' | 'needs_authorization' (Agent 12's verdict, set after Agent 11 logs it)
    applied INTEGER,     -- 1 once the change actually landed on `projects`
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS change_requests (
    -- §7.2.2 — Agent 12 writes here only for updates it evaluated 'needs_authorization'. This is
    -- what makes Manual Gate 3 a real, resolvable gate instead of a named-but-unused table.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_update_id INTEGER,
    original_project_id TEXT, new_project_id TEXT, requested_by TEXT, reason TEXT,
    status TEXT, pmo_comment TEXT, resolved_by TEXT, created_at TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT, recipient TEXT, channel TEXT, subject TEXT, body TEXT, sent_at TEXT,
    trigger_agent TEXT  -- which agent's step caused this to be sent, e.g. "agent7_acceptance_handler"
                        -- (§11) — lets the dashboard show "at which phase" a notification went out.
);
CREATE TABLE IF NOT EXISTS kb_documents (
    -- §7.2.3 adds doc_type='opl' + project_id (null for playbook/pvp/political/regulatory, set for
    -- every 'opl' row) — lets Agent 2/5 trace a similarity hit back to the specific project it came from.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT, project_id TEXT, chunk_text TEXT, version INTEGER, reviewed_by TEXT,
    last_reviewed_at TEXT, is_active INTEGER
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT, agent TEXT, action TEXT, payload TEXT, duration_ms INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS gate2_batches (
    -- §5.3 periodic Gate 2 review — one row per weekly sitting. A Gate 2 decision's own audit_log
    -- payload (not a column here) records gate2_batch_id/exception_reason (see pipeline.py).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at TEXT, closed_at TEXT, opened_by TEXT
);
CREATE TABLE IF NOT EXISTS project_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT, author TEXT, role TEXT, body TEXT,
    is_flagged_concern INTEGER, linked_gate TEXT, created_at TEXT
);
"""

def get_connection(fresh=False):
    if fresh and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
