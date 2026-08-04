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

Runs all 12 phase test files in order (`tests/scenarios/`, `tests/eval/`) and prints pass/fail counts. 189 checks total, covering agents, the state machine, guardrails, the full pipeline across all 10 named scenarios (7 original + 3 batch-queue cases), the post-acceptance change-management/OPL loop, the periodic Gate 2 review queue (now embedded on the topline dashboard), the dashboard/visualizer/comment panel, the topline's metric cards/distribution panels/sortable table, and the composer's freeform "compose your own" submission path. To run one phase at a time:

```
python3 tests/scenarios/test_phase1.py
python3 tests/eval/test_phase2.py
python3 tests/scenarios/test_phase3.py
python3 tests/eval/test_phase4.py
python3 tests/eval/test_phase5.py
python3 tests/scenarios/test_phase6.py    # Agent 11 (Update Logger)
python3 tests/scenarios/test_phase7.py    # Agent 12 (Change Evaluator) + Gate 3
python3 tests/scenarios/test_phase8.py    # Agent 13 (OPL Composer) + Agent 2/5 feedback
python3 tests/scenarios/test_phase9.py    # Periodic Gate 2 Review batching (§5.3)
python3 tests/scenarios/test_phase10.py   # Gate 2 accept-comment + Hold
python3 tests/scenarios/test_phase11.py   # "comparing Foo's repo" upversion — see below
python3 tests/scenarios/test_phase12.py   # composer redesign: dropdown + real freeform submission
```

## Seeing the actual system run — in a browser (recommended)

```
python3 scripts/demo_server.py
```

Starts a local-only server and prints `http://127.0.0.1:8765`. Open that in a browser — the left
panel is a dropdown covering 10 cases: the 7 named scenarios (predrafted submission emails, real
trial data, phrased the way a submitter would write it) plus Case 8/9/10 — post-acceptance change
management (Agents 11/12, one action per case: favorable auto-apply, unfavorable → Gate 3) and
project completion (Agent 13's OPL). Picking one shows its preview and a "Run this case" button;
clicking it sends that submission through the real agent pipeline live, then drops you straight onto
the execution visualizer for the result. Below the dropdown, a "compose your own" box
(From/Subject/Body) runs genuinely typed text through the same real pipeline via Agent 1's actual
parser — see "Mock mode" below for what's genuinely live versus mocked in that path. The portfolio
dashboard (`dashboard/topline.html`) embeds §5.3's Periodic Gate 2 Review queue directly — Open/Close
batch and Review/Override are real buttons there now, not a separate composer entry. Every dashboard
page has a "← Composer" link back to the landing page so you can run another case. Stop the server
with Ctrl+C when you're done.

## Seeing the actual system run — from the terminal

```
python3 scripts/run_demo.py 6_change_request_stakeholder_flag
```

Same underlying engine as the browser composer (`scripts/demo_engine.py`), just triggered from the
command line instead of a click. Seeds the database with all 20 trial projects (`data/trial-projects.json`), runs the chosen scenario through the real pipeline, and renders the dashboard, visualizer, and comment panel from the result. Then open in a browser (double-click from Finder, or drag into a browser tab):

- `dashboard/topline.html` — portfolio dashboard: metric cards (Total Projects, Portfolio value, Approved rate, Avg success likelihood), Status + Strategic Alignment distribution panels, risk mix, needs-attention panel, the embedded Periodic Gate 2 Review queue (§5.3), and a sortable project table (click any column header)
- `dashboard/visualizer_PRJ-2026-0842.html` — the 1-10 agent pipeline as a graph (boxes, gate diamonds, terminal outcomes), replaying the real path this submission took at 5 seconds/step (readable pace, not a race), with a live execution log and a Replay button
- `dashboard/comments_PRJ-2026-0842.html` — comment panel, showing the PMO-vs-stakeholder permission split
- `dashboard/notifications_PRJ-2026-0842.html` — every notification actually sent for this project: registration, acceptance/rejection + reason, and the Agent 10 success forecast
- `dashboard/activity.html` — portfolio-wide feed of every agent step and comment across all 20 records, not scoped to one project

All five pages link to each other (nav bar at the top), so you can start from `topline.html` and click through the whole story for any project. Filenames for the per-project pages depend on which ID the run ended up with — rejected/duplicate/incomplete runs never get a `PRJ-` project ID (they keep their `SUB-xxxx` submission ID instead), so check the "Rendered:" lines the script prints for the exact filenames.

All 7 scenario keys (see `data/trial-projects.json`'s `scenario_index`, or §12 in the tech spec):
`1_accepted_aligned_low_capex_high_price`, `2_rejected_duplicate_exists`, `3_rejected_misaligned_business_direction`,
`4_under_review_unknown_regulatory_risk`, `5_rejected_incomplete_information`, `6_change_request_stakeholder_flag`,
`7_borderline_duplicate_llm_adjudication`.

## Mock mode

`src/llm/client.py` runs in mock mode whenever `ANTHROPIC_API_KEY` isn't set in the environment — every agent call returns a hand-written, hand-verified mock response instead of hitting a real model. This is how all 159 tests pass without spending any credits. Setting a real `ANTHROPIC_API_KEY` switches to live Claude calls automatically; no code changes needed.

Two optional, additive upgrades on top of mock mode — both off by default, both fall back cleanly if unset or if the real call fails, neither changes any existing test:

- **`USE_OLLAMA_EMBEDDINGS=1`** — Agent 2's duplicate check uses real local embeddings via [Ollama](https://ollama.com) instead of the default TF-IDF stand-in (`src/llm/embeddings.py`). Requires Ollama actually running locally:
  ```
  ollama serve                    # starts the local daemon (default port 11434)
  ollama pull all-minilm          # one-time model download (~46MB, the default model)
  export USE_OLLAMA_EMBEDDINGS=1
  python3 scripts/demo_server.py
  ```
  Absent the env var, or if Ollama isn't running / times out / the model isn't pulled, Agent 2 falls straight back to TF-IDF automatically — no crash, no hang (3-second timeout by default, tunable via `OLLAMA_TIMEOUT_SECONDS`). Model is configurable via `OLLAMA_EMBED_MODEL` if you'd rather use something like `embeddinggemma` or `qwen3-embedding` (see [Ollama's embedding models](https://docs.ollama.com/capabilities/embeddings)).
- Agent 1's intake parser now has a real deterministic fallback (`src/agents/agent1_intake_parser.py`'s `_deterministic_fallback_parse`) for genuinely unscripted input in mock mode, instead of raising an error. Nothing to configure — it only engages when no `mock_response` was supplied. This is exactly what the composer's "compose your own" box calls live — nothing to set up beyond running the server normally.

All three came out of a deliberate comparison against a teammate's repo (the first two directly; the composer redesign is a later, related pass), documented in full — what was adopted, what wasn't, and exactly how to revert — in `docs/comparing-foos-repo.md`. (The embeddings upgrade originally used a hosted API, Voyage AI, before being swapped to Ollama — same doc explains why.)

## Project layout

- `TECH-SPEC.md` — full architecture and design decisions, the source of truth
- `BUILD-TASKS.md` — the 6-phase build plan, checked off against real passing tests
- `PORTING.md` — exact steps to move this build into CodeBuddy
- `SUBMISSION-CHECKLIST.md` — hackathon submission requirements, mapped to what's ready
- `DEMO-TRANSCRIPT.md` — shot list for the required demo video, generated from a real run
- `data/` — 20 synthetic trial projects (curated, no template duplicates — see `docs/comparing-foos-repo.md`), Playbook, PVP, political, and regulatory docs
- `src/` — agents, orchestration (state machine, guardrails), db, notifications, LLM client (`src/llm/client.py` for text, `src/llm/embeddings.py` for the optional real-embeddings backend)
- `scripts/demo_engine.py` — shared logic for running a scenario (seeding, pipeline, rendering); `demo_server.py` (browser composer) and `run_demo.py` (CLI) both call into it
- `dashboard/` — rendered HTML output (topline, visualizer, comments, notifications, activity feed)
- `tests/` — the 189 acceptance checks across all 12 build phases
- `docs/comparing-foos-repo.md` — the teammate-repo comparison this session's upversion came from: what was adopted, what was deliberately skipped, and the exact rollback plan
