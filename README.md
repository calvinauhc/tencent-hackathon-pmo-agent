# PMO Project Intake & Governance Agent

AI-powered project intake and governance system for a PMO — built for the AIT x Tencent Cloud Hackathon (Business Agent track). Full design in `TECH-SPEC.md`; this file is just setup and how to run things.

## Setup (macOS with Homebrew Python)

macOS locks down system Python (PEP 668), so pip needs a virtual environment. Run these once, in this folder:

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Each time you come back to work on this in a new Terminal tab, re-run `source venv/bin/activate` first — the venv only needs to be created once, but activation is per-session. You'll know it's active when your prompt shows `(venv)`.

No API key is required to run or test this build — it runs in mock mode automatically (see "Mock mode" below).

## Running the tests

```
./run_all_tests.sh
```

Runs all 5 phase test files in order (`tests/scenarios/`, `tests/eval/`) and prints pass/fail counts. 54 checks total, covering agents, the state machine, guardrails, the full pipeline across all 7 named scenarios, and the dashboard/visualizer/comment panel. To run one phase at a time:

```
python3 tests/scenarios/test_phase1.py
python3 tests/eval/test_phase2.py
python3 tests/scenarios/test_phase3.py
python3 tests/eval/test_phase4.py
python3 tests/eval/test_phase5.py
```

## Seeing the actual system run — in a browser (recommended)

```
python3 scripts/demo_server.py
```

Starts a local-only server and prints `http://127.0.0.1:8765`. Open that in a browser — it's a
composer landing page with all 7 named scenarios shown as predrafted submission emails (real trial
data, phrased the way a submitter would write it). Click "Run this case" on any of them and it
sends that submission through the real agent pipeline live, then drops you straight onto the
execution visualizer for the result. Every dashboard page has a "← Composer" link back to the
landing page so you can run another case. Stop the server with Ctrl+C when you're done.

## Seeing the actual system run — from the terminal

```
python3 scripts/run_demo.py 6_change_request_stakeholder_flag
```

Same underlying engine as the browser composer (`scripts/demo_engine.py`), just triggered from the
command line instead of a click. Seeds the database with all 100 trial projects (`data/trial-projects.json`), runs the chosen scenario through the real pipeline, and renders the dashboard, visualizer, and comment panel from the result. Then open in a browser (double-click from Finder, or drag into a browser tab):

- `dashboard/topline.html` — portfolio dashboard: metric cards, risk mix, needs-attention panel, project table
- `dashboard/visualizer_PRJ-2026-0842.html` — the 1-10 agent pipeline as a graph (boxes, gate diamonds, terminal outcomes), replaying the real path this submission took at 5 seconds/step (readable pace, not a race), with a live execution log and a Replay button
- `dashboard/comments_PRJ-2026-0842.html` — comment panel, showing the PMO-vs-stakeholder permission split
- `dashboard/notifications_PRJ-2026-0842.html` — every notification actually sent for this project: registration, acceptance/rejection + reason, and the Agent 10 success forecast
- `dashboard/activity.html` — portfolio-wide feed of every agent step and comment across all 100 records, not scoped to one project

All five pages link to each other (nav bar at the top), so you can start from `topline.html` and click through the whole story for any project. Filenames for the per-project pages depend on which ID the run ended up with — rejected/duplicate/incomplete runs never get a `PRJ-` project ID (they keep their `SUB-xxxx` submission ID instead), so check the "Rendered:" lines the script prints for the exact filenames.

All 7 scenario keys (see `data/trial-projects.json`'s `scenario_index`, or §12 in the tech spec):
`1_accepted_aligned_low_capex_high_price`, `2_rejected_duplicate_exists`, `3_rejected_misaligned_business_direction`,
`4_under_review_unknown_regulatory_risk`, `5_rejected_incomplete_information`, `6_change_request_stakeholder_flag`,
`7_borderline_duplicate_llm_adjudication`.

## Mock mode

`src/llm/client.py` runs in mock mode whenever `ANTHROPIC_API_KEY` isn't set in the environment — every agent call returns a hand-written, hand-verified mock response instead of hitting a real model. This is how all 54 tests pass without spending any credits. Setting a real `ANTHROPIC_API_KEY` switches to live Claude calls automatically; no code changes needed.

## Project layout

- `TECH-SPEC.md` — full architecture and design decisions, the source of truth
- `BUILD-TASKS.md` — the 6-phase build plan, checked off against real passing tests
- `PORTING.md` — exact steps to move this build into CodeBuddy
- `SUBMISSION-CHECKLIST.md` — hackathon submission requirements, mapped to what's ready
- `DEMO-TRANSCRIPT.md` — shot list for the required demo video, generated from a real run
- `data/` — 100 synthetic trial projects, Playbook, PVP, political, and regulatory docs
- `src/` — agents, orchestration (state machine, guardrails), db, notifications, LLM client
- `scripts/demo_engine.py` — shared logic for running a scenario (seeding, pipeline, rendering); `demo_server.py` (browser composer) and `run_demo.py` (CLI) both call into it
- `dashboard/` — rendered HTML output (topline, visualizer, comments, notifications, activity feed)
- `tests/` — the 54 acceptance checks across all 5 build phases
