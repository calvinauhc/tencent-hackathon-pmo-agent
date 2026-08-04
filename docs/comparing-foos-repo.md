# Comparing Foo's repo — teammate comparison and upversion record

**"Foo" = a hackathon teammate's separate submission**, [THENGFY/Transform-Office-Workflow](https://github.com/THENGFY/Transform-Office-Workflow) (Enterprise PMO Multi-Agent System, Agents 1-6). Reviewed as a real code-level comparison (cloned and read, not just skimmed on GitHub) to find anything worth adopting before submission.

This doc exists so that if any of this needs to be reverted later — for any reason — the next person (or a future session) doesn't have to reconstruct *why* these changes exist or *what exactly* to undo. Read this before touching anything described below.

## Revision history on this doc

This upversion happened in two passes, not one — worth knowing before you read "What was adopted" below at face value:

1. **First pass** (tag `submission-stable-v1` → merged to `main`): real embeddings for Agent 2 built against **Voyage AI**, a hosted API, specifically chosen *to avoid* a local-daemon dependency like Ollama's.
2. **Second pass** (tag `pre-ollama-swap` on top of that merge, branch `ollama-embeddings-swap`): after further discussion, the user explicitly chose to accept the local-daemon dependency after all — in exchange for zero API cost and zero network calls at inference time — on the condition that TF-IDF is the backup if Ollama isn't responding. `src/llm/embeddings.py` was rewritten to call **Ollama** instead of Voyage. The external contract Agent 2 depends on (`REAL_EMBEDDINGS_AVAILABLE`, `get_embeddings()`) didn't change, so `agent2_duplicate_checker.py` itself needed no changes for this swap.

Everything below describes the **current** (Ollama) state unless marked otherwise. If you need the Voyage version back for any reason, it's fully intact at tag `pre-ollama-swap`.

## Rollback — do this first if you need to revert

```bash
git tag                          # confirm submission-stable-v1 AND pre-ollama-swap both exist
git log --oneline main..comparing-foos-repo        # everything the first pass added, if that branch is unmerged
git log --oneline main..ollama-embeddings-swap      # everything the Ollama swap added, if that branch is unmerged
```

- **Revert everything from both passes, back to before either upversion:** `git checkout main && git reset --hard submission-stable-v1`.
- **Keep the real-embeddings feature but go back to Voyage instead of Ollama:** `git checkout main && git reset --hard pre-ollama-swap` (only safe if nothing else has been built on top since — check `git log` first).
- **Back out only part of it, keeping everything built afterward intact:** `git revert <merge-commit-sha>` is safer than a hard reset either way.
- **Fastest partial revert, no git needed at all:** everything shipped here is off by default and additive (see "How this was built to be revertible" below). Simply don't set `USE_OLLAMA_EMBEDDINGS`, and the system behaves exactly as it did at `submission-stable-v1` — the code can stay merged and simply go unused.

## Scoring framework used to judge what was worth adopting

Per `TECH-SPEC.md` §1 — this is the actual hackathon rubric, not a generic code-quality opinion:

| Dimension | Weight |
|---|---|
| AI Innovation | 30% |
| Technical Excellence | 20% |
| UX & Demo | 25% |
| Business Value & Viability | 25% |

## What Foo's repo does well (the full comparison)

Four things stood out as genuinely worth knowing about, in priority order against the weights above:

1. **Real embeddings for duplicate detection** — Ollama's local `nomic-embed-text` + a persisted ChromaDB store. Real vector similarity, free, offline. Directly relevant: our own `agent2_duplicate_checker.py` docstring already called TF-IDF "a demo-scope stand-in... swap for a real embedding model when porting to CodeBuddy" — this closes a gap we'd already identified ourselves.
2. **A real LLM call path with graceful multi-tier fallback** — Agent 1 tries Gemini, then OpenAI, then a genuine deterministic regex parser, never crashing. Our own `src/llm/client.py` already had a real Anthropic tier (just never exercised in this sandbox), but our mock-mode "fallback" was a hard crash if no `mock_response` was hand-authored — it could only ever process pre-scripted input, never anything novel.
3. **Live inbound email intake** (Gmail IMAP listener, polling every 10s, with a graceful "Simulation Mode" fallback when no password is set) — a real intake channel, not a dropdown of canned scenarios. Strong Business Value & Viability / UX & Demo proof point.
4. **Runtime CAG document upload portal** — drag-and-drop upload for governance docs at runtime instead of fixed flat files.

Everything else that differs (narrower 6-agent scope vs. our 13, LangChain LCEL orchestration vs. our hand-rolled state machine, single-page live FastAPI dashboard vs. our replay-visualizer composer, their `PRJ-YYYY-DDD` chronological ID rule, Pydantic per-agent-output schemas vs. our dict + `validate_enum()` guardrails) is a different design choice, not something scoring-relevant to copy. Not adopted, not because it's bad, but because it isn't a gap.

**LangSmith was also considered and explicitly rejected** (see conversation this doc was extracted from): Foo isn't using it despite using LangChain, so it wasn't even a real gap versus his repo. We already have a purpose-built equivalent (`audit_log` + the Live Execution Visualizer, §9.1) that's a stronger UX & Demo asset than a generic trace-tree would be, and adopting it would mean either taking on LangChain wholesale or bolting on a backend-only dev tool that doesn't move any of the four scored dimensions.

## What was adopted here, and exactly what changed

Only items #1 and #2 above were built. #3 and #4 were judged lower priority given time before submission and left undone (see "Explicitly not built" below).

### 1. Real embeddings for Agent 2 (`src/llm/embeddings.py`, new file)

**Current state (second pass): Ollama, matching Foo's choice directly.** `nomic-embed-text` was his model; this defaults to `all-minilm` instead (smaller/faster pull, ~46MB, good for a demo machine — configurable via `OLLAMA_EMBED_MODEL` if you want his exact model or something larger like `embeddinggemma`/`qwen3-embedding`). Requires `ollama serve` running locally and the model pulled — see README.md's Mock mode section for the exact commands.

**First pass deliberately avoided this** (see "Revision history" above) — Ollama needs a local daemon running on whatever machine actually demos this, a real external dependency this project has no way to guarantee at judging time, breaking the existing "just run one script" demo-reliability property. That risk is exactly why Voyage AI (a hosted API) was chosen first. **The user explicitly re-evaluated and accepted that risk** in exchange for zero ongoing API cost and zero network calls at inference time, on one hard condition: **TF-IDF must be the backup if Ollama isn't responding.** That condition was already guaranteed by the architecture built in the first pass — `agent2_duplicate_checker.py`'s fallback logic doesn't know or care which real backend is behind `get_embeddings()`, it just catches any failure and falls back. So the swap only touched `src/llm/embeddings.py` internals; the safety guarantee didn't need to be rebuilt.

The other rejected local option from the first pass, `sentence-transformers` (pulls in PyTorch, likely 300-500MB), is still not used — Ollama was the more direct match to what was actually requested.

**Behavior (same contract both passes, only the real backend changed):**
- `USE_OLLAMA_EMBEDDINGS` unset (the default) → `REAL_EMBEDDINGS_AVAILABLE = False` → `agent2_duplicate_checker.find_closest_match()` behaves **exactly** as it did before either upversion pass — TF-IDF + cosine, byte-for-byte. All 140 pre-existing tests pass completely untouched.
- `USE_OLLAMA_EMBEDDINGS=1` set → real embedding call attempted first (`POST http://localhost:11434/api/embed`, a 3-second default timeout so a dead daemon can't hang a live demo — tunable via `OLLAMA_TIMEOUT_SECONDS`); **any failure** (daemon not running, timeout, model not pulled, malformed response) is caught, logs a warning, and falls back to TF-IDF rather than crashing duplicate-checking.
- `src/agents/agent2_duplicate_checker.py` itself: unchanged by the Ollama swap. `find_closest_match()` still tries `_real_embedding_similarities()` first, only computing TF-IDF if that returns `None` — exactly as built in the first pass.

**Not independently verified against a real running Ollama instance.** This sandbox's network allowlist blocks `ollama.com`, so the binary/model couldn't be installed here to test end-to-end. Verified instead via careful reading of Ollama's own `/api/embed` documentation and thorough monkeypatched tests (`tests/scenarios/test_phase11.py`, checks 11.2b/11.2c) that construct the exact request Ollama expects and parse the exact response shape it returns — but the very first real run needs to happen on a machine with Ollama actually installed, not assumed to already work from this alone.

**CodeBuddy porting note added** to `TECH-SPEC.md` §4: this is now a real, working bridge toward the pgvector production target, not just a documented intention — the remaining gap is persisting vectors in `kb_documents` instead of recomputing per call.

### 2. Agent 1 harness hardening (`src/agents/agent1_intake_parser.py`)

**Design deliberately differs from Foo's approach.** He built a full multi-provider LLM cascade (Gemini → OpenAI → regex). Not copied wholesale — `src/llm/client.py` is shared infrastructure every agent depends on, and rewriting it this close to submission was judged too broad a change for the value it'd add. Scoped instead to exactly the gap that mattered:

- **`_deterministic_fallback_parse()`** — a real regex-based extractor matching this project's own submission-email format (see `scripts/demo_engine.py`'s `SCENARIO_EMAILS`), not a stub. Extracts `submitter_name`, `team_members`, `objective`, `project_name`, `solution`, `business_impact_usd`, `capex_usd`, `hypothesis_risk`.
- **When it triggers:** only when `llm.call()` raises `RuntimeError` (mock mode, no `mock_response` supplied — i.e., genuinely unscripted input) or returns the `{"raw_text": ...}` shape (a real call succeeded at the network level but returned non-JSON). Every existing test always supplies a `mock_response`, so none of them ever touch this path — confirmed via full suite run, zero regressions.
- **Full `incomplete_fields` audit** added to `parse_intake()`'s return value — computed identically regardless of whether the result came from a real call, a scripted mock, or the fallback parser. Mirrors Foo's `ProjectSubmission.calculate_incomplete_fields()` self-audit, without adopting Pydantic (kept consistent with this codebase's existing hand-rolled `validate_enum()` guardrail style in `src/shared/schemas.py` rather than introducing a new framework dependency).

**Important honesty note, not a change made:** `parse_intake()` is exercised directly by `tests/scenarios/test_phase1.py` and `test_phase11.py`, but the **live demo pipeline does not call it**. `src/orchestration/pipeline.py` only reuses Agent 1's `REQUIRED_FIELDS` constant for its own validation step against an already-structured `Project` object — the composer/trial-data flow never routes raw text through this function today. This hardening is real, tested, working code that matches what Agent 1 is speced to do (§2) once raw email/form intake is wired up for real (the CodeBuddy port target), but it does not change anything visible in the current demo. Don't oversell this in a pitch as "the live system now handles arbitrary email" — it doesn't yet, this just means it *can* without crashing, the day something starts calling it with real traffic.

### 3. Documentation updates

- `README.md` — "Mock mode" section documents both opt-in upgrades; stale test counts corrected (54→159, 5→11 phases, 7→10 scenarios) while in there.
- `TECH-SPEC.md` §4 — real-embeddings bridge documented against the pgvector production target.
- `TECH-SPEC.md` §16 — A1/A2 rows in the per-agent strategy table updated with the new fallback/embedding behavior.

## Explicitly not built (and why)

- **Gmail IMAP listener** — genuinely good, would need real inbox credentials and ongoing maintenance (a live demo dependency on an actual mailbox being reachable at judging time is its own reliability risk, the same category of concern that ruled out Ollama above). Left for later if there's time.
- **Runtime CAG document upload portal** — low effort to add (Agent 6 already reads flat files from `data/`; an upload endpoint writing into that folder gets most of the value), but judged lower priority than the two harness items above given limited remaining time.
- **LangSmith** — see "What Foo's repo does well" above. Actively decided against, not just deferred.
- **ChromaDB** — Ollama was adopted for the embedding model itself (second pass, see "Revision history" above), but not Foo's ChromaDB vector store alongside it. Vectors are recomputed per call, not persisted — matches this build's existing TF-IDF behavior and keeps the change scoped to "swap the similarity backend," not "add a new persistent store." A real vector column (`kb_documents`, pgvector) is still the actual CodeBuddy-port target either way (§4).
- **sentence-transformers** — considered for the embeddings work and rejected in favor of a hosted API in the first pass, then superseded by Ollama in the second; see item 1 above for the full reasoning trail.
- **Adopting LangChain / Pydantic wholesale** — both would be larger architectural changes than the value they'd add this close to a deadline, given this codebase already has working equivalents (hand-rolled state machine + guardrails; `validate_enum()`).

## How this was built to be revertible

Two layers, matching the plan agreed before any code was touched:

1. **Git-level:** tag `submission-stable-v1` on `main` before the first pass started (branch `comparing-foos-repo`); a second tag `pre-ollama-swap` before the Ollama swap started (branch `ollama-embeddings-swap`), once the first pass was already merged and pushed. Two tags, two independent rollback points — see "Revision history" and "Rollback" above.
2. **Code-level (the one that matters mid-demo):** every change here is additive and gated by an environment variable that defaults to "off, behave exactly as before." No existing code path's default behavior changed, in either pass. This was verified, not assumed — the full 140-check suite that existed before either pass still passes unmodified, plus checks in `tests/scenarios/test_phase11.py` covering the new paths specifically (including the failure/fallback behavior, not just the happy path) — 19 checks after the first pass, 26 after the Ollama swap added request/response-contract coverage.

## Test evidence

`./run_all_tests.sh` — 166/166 checks passed across 11 phases (140 pre-existing + 26 in Phase 11, updated for the Ollama swap) as of this upversion. Phase 11 specifically covers: default behavior unchanged with `USE_OLLAMA_EMBEDDINGS` unset, `_truthy()`'s env-var parsing, `get_embeddings()` refusing to fake a vector, a monkeypatched-at-the-`urllib`-level check that the real request matches Ollama's documented `/api/embed` contract exactly (URL, method, body shape, timeout) and that the response's `embeddings` key is parsed correctly, a malformed/short response raising instead of silently mismatching vectors to projects, the real-embeddings path actually being exercised and picking the correct match under a monkeypatched backend, a simulated failure falling back to TF-IDF instead of crashing, the deterministic fallback parser's field extraction against a realistic email, `parse_intake()` no longer crashing on unscripted input, and scripted-mock behavior being completely unchanged (regression guard). What this suite does **not** cover: an actual live call to a running Ollama daemon — see "Not independently verified" under item 1 above.
