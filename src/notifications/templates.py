"""
Notification templates — §11. Simulated channel (§0): lands in the `notifications` table,
not a real inbox. Internal vs requester-facing naming convention (§11) is centralized here
so the two label sets never drift apart.
"""

AGENT_DISPLAY_NAMES = {
    "agent5_business_impact": "Financial Impact Analyst (Agent 5)",
    "agent6_knowledge_crosscheck": "Corporate Governance Safeguard (Agent 6)",
}

def submission_received(project_name: str) -> dict:
    """§11 — the very first response any submission gets, sent unconditionally the instant it lands
    (before Agent 1's required-field check or anything downstream has run). Every other notification
    (acceptance, rejection — incomplete/duplicate/misaligned, under-review-inconclusive) follows
    later once the actual pipeline has processed it; this one fires for every case, including ones
    that end up rejected, so the originator always hears something back right away."""
    body = (
        f"Thank you for submitting \"{project_name}\" to the Enterprise Project Management Office "
        f"(PMO).\n\nYour submission has been received and is now under review. We will follow up "
        f"with next steps as soon as the review is complete.\n\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Submission received — \"{project_name}\" is under review", "body": body}

def duplicate_rejection(project_name: str, original_project_id: str, original_owner: str) -> dict:
    body = (
        f"Thank you for submitting \"{project_name}\".\n\n"
        f"This appears to duplicate an existing project, {original_project_id}, owned by {original_owner}. "
        f"Please reach out to them to coordinate before resubmitting.\n\n"
        f"Best regards,\nEnterprise PMO team"
    )
    return {"subject": f"Submission not registered — duplicate of {original_project_id}", "body": body}

def intake_acknowledgment(project_name: str, project_id: str) -> dict:
    """Reference implementation — matches the real acknowledgment email verbatim in structure."""
    body = (
        f"Thank you for submitting your proposal \"{project_name}\" to the Enterprise Project "
        f"Management Office (PMO).\n\n"
        f"We have registered your submission under Project ID: {project_id}.\n\n"
        f"Your proposal is currently undergoing evaluation by our {AGENT_DISPLAY_NAMES['agent5_business_impact']} "
        f"and {AGENT_DISPLAY_NAMES['agent6_knowledge_crosscheck']}.\n\n"
        f"We will notify you as soon as the PMO committee completes their review.\n\n"
        f"Best regards,\n\nEnterprise PMO team"
    )
    return {"subject": f"Project registered — {project_id}", "body": body}

def pmo_new_submission_alert(project_name: str, submitter_name: str, project_id: str) -> dict:
    """§2 agent-responsibility table, row 4: "PMO Router ... Notify PMO inbox; awaits manual gate 1" —
    Agent 4's primary job is alerting PMO that a new application needs their attention, which is a
    separate, internal notification from intake_acknowledgment() (sent to the submitter, matches the
    §11 reference acknowledgment structure verbatim — that one stays as-is). This is the one that
    actually lands in the PMO's queue rather than the requester's inbox."""
    body = (
        f"A new project submission has been received and requires PMO awareness.\n\n"
        f"Project: \"{project_name}\" ({project_id})\n"
        f"Submitted by: {submitter_name}\n\n"
        f"Agent 5 (Business Impact) and Agent 6 (Knowledge Cross-Check) are now analyzing it. It "
        f"will reach Manual Gate 2 for a PMO accept/reject decision once that analysis completes.\n\n"
        f"— Automated PMO intake system"
    )
    return {"subject": f"New submission for review — {project_name}", "body": body}

def pmo_auto_resolved_alert(project_name: str, project_id: str, submitter_name: str, reason: str) -> dict:
    """PMO-facing visibility notice for a submission that never reached Agent 4/Gate 2 at all —
    duplicate (Agent 2/3) or incomplete (Agent 1) — so it was auto-resolved before PMO ever saw it.
    Distinct from pmo_new_submission_alert() (which promises "Agent 5/6 are now analyzing it" — not
    true here, that would misstate what's actually happening) and purely informational: no PMO
    action is needed, but the inbox should still show every submission that came in, not just the
    ones that made it to a real Gate 2 decision, so submission volume and auto-resolution reasons
    stay visible end to end."""
    body = (
        f"A project submission was received and auto-resolved before reaching PMO review.\n\n"
        f"Project: \"{project_name}\" ({project_id})\n"
        f"Submitted by: {submitter_name}\n\n"
        f"Outcome: {reason}\n\n"
        f"No action is needed — this is a visibility-only notice.\n\n"
        f"— Automated PMO intake system"
    )
    return {"subject": f"Submission auto-resolved before review — {project_name}", "body": body}

def acceptance(project_name: str, project_id: str, dashboard_url: str = "https://pmo.internal/dashboard", pmo_comment: str = "") -> dict:
    """`pmo_comment` mirrors rejection_feedback()'s optional PMO note (§9.3.4) — same additive
    pattern, not a replacement for anything else in the body. Lets a PMO attach a positive note or
    a watch-out (e.g. "keep an eye on the Q3 headcount dependency") on top of a plain accept."""
    body = (
        f"Good news — \"{project_name}\" has been accepted.\n\n"
        f"Project ID: {project_id}\n"
        f"Track progress on the dashboard: {dashboard_url}\n"
        + (f"\nPMO note: {pmo_comment}\n" if pmo_comment else "")
        + f"\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Accepted — {project_id}", "body": body}

REJECTION_IMPROVEMENT_TIPS = {
    "Low margins relative to CAPEX required": "Consider a phased rollout to reduce upfront CAPEX, or resubmit with a revised margin projection.",
    "Not aligned with strategic focus regions or product areas": "Review the current Playbook's focus regions and product areas before resubmitting.",
    "High unquantified regulatory risk": "Confirm regulatory exposure with counsel and resubmit with a quantified risk assessment.",
    "Incomplete information provided at intake": "Resubmit with submitter name, a clear objective/pain point, and a description of the proposed solution.",
}

def under_monitoring(project_name: str, project_id: str) -> dict:
    """§7 — sent instead of success_forecast() the moment a project is accepted (Agent 10). A
    project with zero tracking history yet can't be meaningfully scored, so this is honest about
    that rather than handing back a number that doesn't mean anything yet (§ SUCCESS_PREDICTOR_MIN_AGE_DAYS)."""
    body = (
        f"\"{project_name}\" ({project_id}) has entered tracking.\n\n"
        f"Status: Under monitoring — a success forecast isn't available yet. Once this project has "
        f"been active long enough to accrue real financial, milestone, and resource tracking data, "
        f"Agent 10 will start scoring it on the dashboard.\n\n"
        f"Best regards,\nEnterprise PMO team"
    )
    return {"subject": f"Under monitoring — {project_id}", "body": body}

def success_forecast(project_name: str, project_id: str, success_score: float, risk_indicator: str) -> dict:
    """§7 Success Predictor output, surfaced to the stakeholder — not just left in the DB.
    This is the notification the old build was missing entirely: Agent 10 computed a score but
    nothing ever told the stakeholder about it."""
    body = (
        f"An updated success forecast is available for \"{project_name}\" ({project_id}).\n\n"
        f"Predicted success score: {success_score}/100\n"
        f"Current risk indicator: {risk_indicator}\n\n"
        f"This score weighs financial, milestone, and resource tracking completeness against the "
        f"project's current risk level (§7). It will update as tracking data comes in.\n\n"
        f"Track live updates on the dashboard.\n\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Success forecast — {project_id} ({success_score}/100)", "body": body}

_FIELD_LABELS = {
    "expected_launch_date": "Expected launch",
    "capex_usd": "CAPEX",
    "risk_indicator": "Risk indicator",
    "schedule_status": "Schedule status",
    "resource_indicator": "Resource indicator",
}

def _format_change_lines(before_state: dict, after_state: dict) -> str:
    lines = []
    for field, after_val in after_state.items():
        label = _FIELD_LABELS.get(field, field)
        before_val = before_state.get(field)
        if field == "capex_usd":
            before_val = f"${before_val:,.0f}" if before_val is not None else "—"
            after_val = f"${after_val:,.0f}" if after_val is not None else "—"
        lines.append(f"  {label}: {before_val} → {after_val}")
    return "\n".join(lines)

def change_auto_applied(project_name: str, project_id: str, before_state: dict, after_state: dict, reason: str) -> dict:
    """§7.2.2 — Agent 12's favorable path. Informational, PMO-facing: no action needed, this is a
    record of what changed and why it didn't need a Gate 3 decision."""
    body = (
        f"An update to \"{project_name}\" ({project_id}) was auto-applied — no PMO action needed.\n\n"
        f"{_format_change_lines(before_state, after_state)}\n\n"
        f"Why this applied automatically: {reason}.\n\n"
        f"— Automated PMO change management (Agent 12)"
    )
    return {"subject": f"Auto-applied update — {project_id}", "body": body}

def change_authorized(project_name: str, project_id: str, after_state: dict, pmo_comment: str = "") -> dict:
    """§7.2.2 — Gate 3 accept. Requester-facing: the change PMO just authorized is now live."""
    body = (
        f"Your requested update to \"{project_name}\" ({project_id}) has been authorized by PMO and is now live.\n\n"
        f"{_format_change_lines({}, after_state)}\n"
        + (f"\nPMO note: {pmo_comment}\n" if pmo_comment else "")
        + f"\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Update authorized — {project_id}", "body": body}

def change_declined(project_name: str, project_id: str, reason: str, pmo_comment: str = "") -> dict:
    """§7.2.2 — Gate 3 reject. Requester-facing: the live project is unchanged."""
    body = (
        f"Your requested update to \"{project_name}\" ({project_id}) was not authorized. The project's "
        f"current values remain unchanged.\n\n"
        f"Reason flagged for PMO review: {reason}\n"
        + (f"PMO note: {pmo_comment}\n" if pmo_comment else "")
        + f"\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Update not authorized — {project_id}", "body": body}

def change_cancelled(project_name: str, project_id: str, reason: str, pmo_comment: str = "") -> dict:
    """§7.2.2 — Gate 3's Cancel decision. Requester-facing: distinct from change_declined() — that one
    means "this specific update wasn't authorized, the project continues unchanged"; this one means
    the project itself has been stopped, typically because the update PMO was reviewing revealed it's
    slipping badly enough on timeline/cost/risk that continuing isn't worth it."""
    body = (
        f"\"{project_name}\" ({project_id}) has been cancelled by PMO.\n\n"
        f"This decision was made while reviewing a project update flagged for authorization "
        f"(reason: {reason}).\n"
        + (f"PMO note: {pmo_comment}\n" if pmo_comment else "")
        + f"\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Project cancelled — {project_id}", "body": body}

def opl_published(project_name: str, project_id: str, opl_url: str) -> dict:
    """§7.2.3 — sent to the project ORIGINATOR once Agent 13 composes and publishes the Operational
    Learnings Package on project completion (Case 10). Distinct from every other template here: this
    one isn't about a decision on the project (accept/reject/authorize/decline/cancel) — it's a
    knowledge-management confirmation that the "what worked / what to reuse" insight future similar
    projects will actually be checked against (§7.2.4, Agent 2/5's OPL-reuse hook) now exists and is
    real, dereferenceable, not just a line item in the DB nobody was told about."""
    body = (
        f"Thanks for confirming \"{project_name}\" ({project_id}) is complete.\n\n"
        f"An Operational Learnings Package (OPL) has been composed and published to the knowledge "
        f"base — it captures what worked, what's worth reusing, and grounded citations from this "
        f"project's real update/change history. It's now part of the corpus future similar "
        f"submissions get checked against, so the lessons from this project can actually help the "
        f"next one, not just sit on file.\n\n"
        f"You can review it here: {opl_url}\n\n"
        f"Best regards,\nEnterprise PMO team"
    )
    return {"subject": f"Project closed out — OPL published for {project_id}", "body": body}

def rejection_feedback(project_name: str, reason: str, pmo_comment: str = "") -> dict:
    tip = REJECTION_IMPROVEMENT_TIPS.get(reason, "Contact PMO for specific improvement guidance.")
    body = (
        f"Your proposal \"{project_name}\" was not accepted at this time.\n\n"
        f"Reason: {reason}\n"
        + (f"PMO note: {pmo_comment}\n\n" if pmo_comment else "\n")
        + f"Suggested next step: {tip}\n\nBest regards,\nEnterprise PMO team"
    )
    return {"subject": f"Update on your proposal: {project_name}", "body": body}
