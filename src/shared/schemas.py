"""
Shared schemas/enums — mirrors TECH-SPEC.md §3 exactly.
Every agent and the db layer import from here; no ad-hoc field names elsewhere.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import time

class Status(str, Enum):
    DRAFT = "draft"
    PMO_REVIEW = "pmo_review"
    ANALYSIS = "analysis"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class RiskCategory(str, Enum):
    REGULATORY = "regulatory"
    FINANCIAL = "financial"
    OPERATIONAL = "operational"
    TECHNOLOGY_IP = "technology_ip"
    MARKET = "market"

class RYG(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

class GateDecision(str, Enum):
    PROCEED = "proceed"
    REJECT = "reject"
    REVIEW = "review"
    ACCEPT = "accept"

# Valid status transitions — §8 state machine. Anything not listed is illegal.
ALLOWED_TRANSITIONS = {
    Status.DRAFT: {Status.PMO_REVIEW, Status.REJECTED},
    Status.PMO_REVIEW: {Status.ANALYSIS, Status.REJECTED},
    Status.ANALYSIS: {Status.ACCEPTED, Status.REJECTED, Status.PMO_REVIEW},  # back to pmo_review if flagged "review"
    Status.ACCEPTED: {Status.IN_PROGRESS},
    Status.IN_PROGRESS: {Status.COMPLETED},
    Status.REJECTED: set(),
    Status.COMPLETED: set(),
}

@dataclass
class Project:
    submission_id: str
    submitter_name: Optional[str] = None
    team_members: list = field(default_factory=list)
    objective: Optional[str] = None
    project_name: Optional[str] = None
    solution: Optional[str] = None
    business_impact_usd: Optional[float] = None
    expected_launch_date: Optional[str] = None  # ISO date "YYYY-MM-DD" — when this initiative expects
    # to go live, if accepted. Feeds Agent 5's margin assessment (playbook.md: "credible path to at
    # least 15% margin within 18 months of launch") — without it, that policy line had nothing real
    # to anchor against.
    hypothesis_risk: Optional[str] = None
    risk_category: Optional[str] = None
    capex_usd: Optional[float] = None
    capex_funded_pct: Optional[float] = None
    status: str = Status.DRAFT.value
    region: Optional[str] = None
    business_unit: Optional[str] = None
    risk_indicator: Optional[str] = None
    schedule_status: Optional[str] = None
    resource_indicator: Optional[str] = None  # RYG — team/staffing availability against what the
    # project needs. Mirrors risk_indicator/schedule_status exactly: a displayed/tracked field, not
    # something any agent computes live (same §7.1 governance guardrail — advisory only, never
    # auto-derived or auto-written by an agent). Visible at Gate 2 (so PMO can see staffing fit
    # before deciding "from the start") and ongoing on the topline dashboard (so a resource
    # constraint surfaces the same way a schedule or risk one would).
    help_needed: Optional[str] = None
    rejection_reason: Optional[str] = None
    success_score: Optional[float] = None
    project_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self):
        return asdict(self)

@dataclass
class AuditLogEntry:
    project_id: str
    agent: str
    action: str
    payload: dict
    duration_ms: int
    created_at: float = field(default_factory=time.time)

@dataclass
class Comment:
    project_id: str
    author: str
    role: str
    body: str
    is_flagged_concern: bool = False
    linked_gate: Optional[str] = None
    created_at: float = field(default_factory=time.time)


def validate_enum(value, enum_cls, field_name):
    """§8.2 guardrail 2 — output schema enforcement. Never coerce, reject and route to manual review."""
    if value is None:
        return None
    try:
        return enum_cls(value).value
    except ValueError:
        raise ValueError(f"REJECTED (not coerced): '{value}' is not a valid {field_name}. "
                          f"Route to manual review, do not guess.")
