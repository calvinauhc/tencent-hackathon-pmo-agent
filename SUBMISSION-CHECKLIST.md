# Submission checklist (per the Participant Handbook)

Status legend: [x] ready · [ ] needs a human to do it — nothing here is fake-completed.

- [ ] **Project title** — draft: "PMO Project Intake & Governance Agent" (confirm before submitting).
- [ ] **Project image** (16:9, ~380×216px) — not created. Recommend a screenshot of `dashboard/topline.html` or the visualizer mid-replay.
- [ ] **Short blurb** (under 10 words) — draft: "AI PMO intake and governance, from proposal to dashboard." (9 words — trim if needed).
- [ ] **Project description** — four required parts, sourced from TECH-SPEC.md:
  - Project overview / target scenario / value proposition → §13
  - Real-world scenario insights (pain source, audience, core problem) → §13, Agent brief.md
  - Solution design (business + technical architecture, how prompts drive generation) → §2, §5, §8, §16
  - Quantifiable metrics / impact → §13's scaling narrative + real numbers from `dashboard/topline.html` once run against real trial data
- [ ] **Demo video** (3-5 min) — shot list ready in `DEMO-TRANSCRIPT.md`, generated from a real run, not scripted fiction. Recording itself is a manual step.
- [ ] **Product Sharing paragraph** — how CodeBuddy was used, one paragraph. Write this *after* the CodeBuddy port (`PORTING.md`), not before — it needs to be a real account of that experience, not a prediction of one.
- [ ] **Project link** (optional/bonus) — pending a hosted deployment; not part of this local build.

## Pitch Day (only if Top 8)

- [ ] Pitch deck (5 min presentation + 5 min Q&A)
- [ ] Live-runnable demo — use `scripts/run_demo.py` + the rendered dashboard/visualizer/comment HTML, live. Screen recording (from `DEMO-TRANSCRIPT.md`'s run) is the fallback only, per §12.1.
- [ ] Project brief: scenario, technical architecture, business value — same sources as the description above.

## What's already real and ready to point to

- `TECH-SPEC.md` — full architecture, judged against all four scoring dimensions (§1).
- `BUILD-TASKS.md` — 6 phases, all checked off against real passing tests (see below).
- `data/` — 100 synthetic trial projects + Playbook, PVP, political, and regulatory docs.
- `src/` — working agents (1, 2, 5, 6, 7, 8, 10, 7.1), state machine, guardrails, audit log — all covered by `tests/`.
- `dashboard/` — topline dashboard, replay visualizer, comment panel, all rendering from real pipeline output, not mockups.
- `DEMO-TRANSCRIPT.md` — the real shot list for the required video, generated from an actual run.
