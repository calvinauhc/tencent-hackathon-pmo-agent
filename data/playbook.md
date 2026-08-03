# Company Playbook (Synthetic — Trial Data)

Status: synthetic demo data, not a real company document (per TECH-SPEC.md §8.2 guardrail #5 — no real company data in trial docs).

## Business Context

Meridian Holdings is a generic multi-region enterprise operating across Technical (Operations, Regulatory, Quality, Engineering, R&D) and Commercial (Finance, Sales, Marketing) functions. This playbook sets the direction PMO uses to evaluate incoming project proposals for strategic alignment.

## Focus Regions

- **Priority:** Southeast Asia, North America
- **Selective:** Europe (only for regulatory/compliance-driven projects)
- **Not currently in scope:** Expansion into new, unentered regions without an existing operating base

## Product / Technology Investment Areas

- **Priority:** AI-enabled operational tooling, supply chain digitization, customer-facing automation
- **Selective:** Hardware/CAPEX-heavy manufacturing upgrades (case-by-case, requires strong ROI case)
- **Not currently in scope:** Consumer-facing new product lines outside existing verticals; speculative R&D with no defined commercial path within 24 months

## Investment Thresholds (for Business Impact scoring, §5/A5)

- Projects under USD 50K: fast-tracked, minimal PMO review
- USD 50K–500K: standard review, requires margin and CAPEX justification
- Above USD 500K: full review, requires executive sponsor named at intake

## Margin Expectations

New initiatives are expected to demonstrate a credible path to at least 15% margin within 18 months of launch, unless explicitly framed as a strategic loss-leader with named executive approval.

## Regional CAPEX Budgets

Each priority/selective region (see Focus Regions above) has an annual CAPEX pool. Agent 5 checks a new project's CAPEX against the region's remaining headroom (already-accepted + in-progress CAPEX for that region) and flags Gate 2 if accepting it would push the region over budget — this is informational, not a block; PMO still makes the final call.

| Region | Annual CAPEX budget |
|---|---|
| Southeast Asia | $1,200,000 |
| North America | $1,500,000 |
| Europe | $650,000 (selective scope only, per Focus Regions above) |
| Other / not-in-scope regions | $800,000 (legacy/exception commitments only — this tier isn't a growth priority) |

PMO owns this table. Change a number here and Agent 5's next run picks it up — no code change needed.

## Portfolio Prioritization (when a region is budget-constrained)

When a region's remaining headroom can't cover every project waiting on a decision, PMO weighs which to accept using one of two lenses — this section is the PMO-editable policy for *when* each lens applies, so the strategy can change without touching code:

- **Lens 1 — Low risk, low CAPEX first.** Favor cheap, low-risk wins over larger bets. Use this lens when a region's committed CAPEX is already close to its budget (headroom under ~15% of the total) — the priority becomes preserving optionality and funding more, smaller approvals rather than committing what's left to one large project.
- **Lens 2 — Best ROI ratio (size of price ÷ CAPEX) first.** Favor whichever project returns the most business impact per CAPEX dollar, regardless of absolute size. Use this lens when a region still has comfortable headroom (over ~15% of the total remaining) — there's room to fund the highest-value project even if it's not the cheapest.

PMO can change these thresholds, swap which lens applies when, or add a third lens entirely by editing this section — Agent 5 reads it fresh on every run, the same way it reads Margin Expectations above.
