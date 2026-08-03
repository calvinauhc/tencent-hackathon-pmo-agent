"""Agent 10 — Success Predictor. §2, §7. No LLM — pure deterministic formula.

Runs "continuous, post-acceptance" per §2's agent table, but a project needs real tracking history
before a score means anything — one accepted an hour ago hasn't accrued financial/milestone/resource
tracking data yet. So: projects younger than SUCCESS_PREDICTOR_MIN_AGE_DAYS (§7 config) are marked
"Under monitoring" instead of scored; only projects that have been in the portfolio at least that
long get an actual number.
"""
import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.config import SUCCESS_SCORE_WEIGHTS, RISK_PENALTY_BY_COLOR, SUCCESS_PREDICTOR_MIN_AGE_DAYS

def compute_success_score(financial_tracking_pct, milestone_tracking_pct, resource_tracking_pct, risk_indicator):
    w = SUCCESS_SCORE_WEIGHTS
    risk_penalty = RISK_PENALTY_BY_COLOR[risk_indicator]
    score = (
        w["financial_tracking"] * financial_tracking_pct
        + w["milestone_tracking"] * milestone_tracking_pct
        + w["resource_tracking"] * resource_tracking_pct
        + w["risk_penalty"] * (1 - risk_penalty) * 100
    )
    return round(score, 1)


def _parse_created_at(created_at):
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return None


def project_age_days(created_at, now=None):
    """Age in days, or None if created_at is missing/unparseable (treated as not-yet-eligible)."""
    created = _parse_created_at(created_at)
    if created is None:
        return None
    now = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 86400


def is_eligible_for_prediction(created_at, now=None):
    age = project_age_days(created_at, now=now)
    return age is not None and age >= SUCCESS_PREDICTOR_MIN_AGE_DAYS


# [ASSUMPTION] this MVP's schema has no explicit financial_tracking_pct/milestone_tracking_pct/
# resource_tracking_pct fields (§3 didn't define separate tracking-percentage columns) — proxy them
# from fields that do exist, rather than inventing new schema for a demo. Ported to CodeBuddy, these
# should become real tracked percentages from actual project-management data, not derived proxies.
_SCHEDULE_MILESTONE_PROXY = {"green": 100, "yellow": 70, "red": 40}

def predict_or_monitor(project, now=None):
    """
    project: dict-like with created_at, risk_indicator, capex_funded_pct, schedule_status, help_needed.
    Returns {"status": "under_monitoring", "success_score": None} for anything younger than
    SUCCESS_PREDICTOR_MIN_AGE_DAYS, or {"status": "predicted", "success_score": <float>} otherwise —
    regardless of whether a success_score happens to already be stored, since a stale/premature
    number shouldn't be shown as if it were a real prediction.
    """
    get = project.get if isinstance(project, dict) else lambda k, d=None: getattr(project, k, d)
    if not is_eligible_for_prediction(get("created_at"), now=now):
        return {"status": "under_monitoring", "success_score": None}

    financial = get("capex_funded_pct") if get("capex_funded_pct") is not None else 100
    milestone = _SCHEDULE_MILESTONE_PROXY.get(get("schedule_status"), 100)
    # resource_indicator (team/staffing availability, §3) is a real tracked RYG field now, same as
    # risk_indicator/schedule_status — use it directly, same 100/70/40 scale as the milestone proxy
    # above. Only fall back to the old help_needed guess for records that predate the field.
    resource_indicator = get("resource_indicator")
    if resource_indicator:
        resource = _SCHEDULE_MILESTONE_PROXY.get(resource_indicator, 100)
    else:
        resource = 60 if get("help_needed") else 100
    risk = get("risk_indicator") or "green"
    score = compute_success_score(financial, milestone, resource, risk)
    return {"status": "predicted", "success_score": score}
