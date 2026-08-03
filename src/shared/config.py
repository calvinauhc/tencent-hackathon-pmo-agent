"""
Centralized [ASSUMPTION] thresholds — TECH-SPEC.md §4, §7, §8.1, §8.3.
Every tunable value lives here, nowhere else. Tune during testing without hunting through agent code.
"""

# §4 duplicate detection thresholds
DUPLICATE_AUTO_FLAG_THRESHOLD = 0.85
DUPLICATE_NOT_DUPLICATE_THRESHOLD = 0.65
# between the two -> borderline, route to LLM adjudication

# §7.2.4 — a not_duplicate match this similar or higher is worth surfacing to Agent 5 as a "similar
# past project" (if that match has a published OPL, §7.2.3), even though it's nowhere near
# duplicate-flag territory. [ASSUMPTION] deliberately looser than DUPLICATE_NOT_DUPLICATE_THRESHOLD —
# best-practice reuse is a much lower bar than "is this the same project."
REUSE_SIMILARITY_THRESHOLD = 0.3

# §5 playbook.md "Margin Expectations": new initiatives are expected to demonstrate a credible path
# to at least 15% margin within this many months AFTER launch (not months-until-launch — the clock
# starts once the project goes live). Centralized here so Agent 5's prompt and any future
# deterministic check reference the same number as the policy text, not a hardcoded duplicate.
MARGIN_WINDOW_MONTHS = 18

# §5 playbook.md "Regional CAPEX Budgets" — annual CAPEX pool per region. Agent 5 sums already-
# accepted/in-progress/completed CAPEX for the project's region and flags Gate 2 if this project
# would push the region over its budget. PMO-editable in playbook.md prose; this dict is the
# machine-readable mirror Agent 5's deterministic check actually reads (kept in sync manually —
# see playbook.md "Regional CAPEX Budgets" table).
REGIONAL_CAPEX_BUDGET_USD = {
    "Southeast Asia": 1_200_000,
    "North America": 1_500_000,
    "Europe": 650_000,
    "Other": 800_000,
}
# §5 playbook.md "Portfolio Prioritization" — headroom-ratio boundary between the two prioritization
# lenses (below this fraction of budget remaining -> low-risk/low-CAPEX lens; above -> best-ROI lens).
# Informational for now (surfaced alongside the budget flag); not yet used to auto-rank projects.
BUDGET_HEADROOM_LENS_THRESHOLD = 0.15

# §5.3 periodic Gate 2 review — batching cadence + the policy-based fast-track exception. No real
# wall clock enforces GATE2_BATCH_INTERVAL_DAYS in this demo (there's no scheduler here, §7.1's
# note about the same gap) — it's documentation of the intended production cadence; PMO opens a
# batch sitting on demand via the composer instead. GATE2_FAST_TRACK_CAPEX_USD mirrors playbook.md's
# existing Investment Thresholds line ("Projects under USD 50K: fast-tracked, minimal PMO review")
# — reused as-is, not a new number invented for batching.
GATE2_BATCH_INTERVAL_DAYS = 7
GATE2_FAST_TRACK_CAPEX_USD = 50000

# §7 success score formula weights
SUCCESS_SCORE_WEIGHTS = {
    "financial_tracking": 0.3,
    "milestone_tracking": 0.3,
    "resource_tracking": 0.2,
    "risk_penalty": 0.2,
}
RISK_PENALTY_BY_COLOR = {"green": 0.0, "yellow": 0.5, "red": 1.0}
# §7.2.2 Agent 12's favorable/unfavorable check — ordinal rank so "reduced risk" is a comparable
# direction (new_rank <= old_rank), not just a label swap. Lower is better, same green<yellow<red
# ordering RISK_PENALTY_BY_COLOR already uses.
RISK_RANK = {"green": 0, "yellow": 1, "red": 2}
# [ASSUMPTION] a project needs at least this long of real tracking history before Agent 10's score
# means anything — a project accepted an hour ago hasn't accrued any financial/milestone/resource
# tracking data yet, so scoring it would just be re-stating its risk_indicator with extra steps.
# Below this age, the dashboard shows "Under monitoring" instead of a number.
SUCCESS_PREDICTOR_MIN_AGE_DAYS = 90

# §8.1 bounded iteration & cost control
MAX_REASONING_TURNS = 3
MAX_RETRIES = 2
PER_AGENT_TIMEOUT_SECONDS = 30

# §8.3 performance SLA targets (seconds)
SLA_TARGETS = {
    "agent1_parse": 5,
    "agent2_duplicate_check": 10,
    "agent5_6_combined": 20,
    "end_to_end_gate1": 60,
}

# §5.1 knowledge base staleness
PLAYBOOK_PVP_STALENESS_DAYS = 90
# §7.1 political/regulatory docs move faster than playbook/pvp
POLITICAL_REGULATORY_STALENESS = "current_calendar_month"

# LLM model routing — §16. "mock" mode used when no ANTHROPIC_API_KEY is set,
# so the pipeline is fully testable without live API access.
MODEL_ROUTING = {
    "agent1_intake_parser": "haiku",
    "agent2_borderline_adjudication": "sonnet",
    "agent5_business_impact": "sonnet",
    "agent6_knowledge_crosscheck": "sonnet",
    "agent8_rejection_feedback": "haiku",
    "agent8_tone_check": "haiku",
    "agent7_1_monthly_briefing": "sonnet",
}
