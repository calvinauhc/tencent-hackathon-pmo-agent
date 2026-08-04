"""
Phase 11 verification — "comparing Foo's repo" upversion: the optional real-embeddings backend for
Agent 2 (src/llm/embeddings.py), and the fallback contract that makes it safe to have merged.

Backend is Ollama (local daemon), not the hosted Voyage AI API this module originally shipped with
— see src/llm/embeddings.py's docstring for why. Cannot call a real Ollama daemon from this test
(this sandbox's network allowlist blocks ollama.com, so nothing could be installed here even for a
one-off manual check) — real end-to-end verification has to happen on a machine with Ollama actually
running, not in CI. Everything here either exercises the real module with the opt-in flag unset (the
default, always-on path, needs no daemon) or monkeypatches urllib/the module itself to simulate a
daemon being present, so the request shape, response parsing, and fallback/failure logic in
agent2_duplicate_checker.py all get real coverage without a network call.
"""
import sys, os, json, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.db.trial_loader import load_trial_data
from src.llm import embeddings as embeddings_backend
import src.agents.agent2_duplicate_checker as agent2
from src.agents.agent1_intake_parser import parse_intake, _deterministic_fallback_parse

results = []
def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}  {detail}")

projects, idx = load_trial_data()
by_id = {p.submission_id: p for p in projects}

# --- 11.1 default state: USE_OLLAMA_EMBEDDINGS not set in this environment ---
check("11.1 REAL_EMBEDDINGS_AVAILABLE is False without the opt-in flag", embeddings_backend.REAL_EMBEDDINGS_AVAILABLE is False, embeddings_backend.REAL_EMBEDDINGS_AVAILABLE)

# --- 11.1b _truthy() parses common "on" spellings and rejects everything else ---
truthy_cases = [("1", True), ("true", True), ("True", True), ("yes", True), ("on", True),
                ("0", False), ("false", False), ("", False), (None, False), ("nope", False)]
truthy_ok = all(embeddings_backend._truthy(v) == expected for v, expected in truthy_cases)
check("11.1b _truthy() correctly parses every case", truthy_ok, truthy_cases)

# --- 11.2 get_embeddings() refuses to silently fake a vector ---
raised = False
try:
    embeddings_backend.get_embeddings(["some text"])
except RuntimeError as e:
    raised = True
    check("11.2 get_embeddings() raises RuntimeError with the flag unset (never fakes a vector)", "USE_OLLAMA_EMBEDDINGS" in str(e), str(e))
check("11.2 get_embeddings() actually raised", raised)

# --- 11.2b get_embeddings() sends the correct request shape to Ollama's real /api/embed contract ---
# (per docs.ollama.com/capabilities/embeddings: POST {model, input}, response has "embeddings")
class _FakeHTTPResponse:
    def __init__(self, body_dict):
        self._body = json.dumps(body_dict).encode("utf-8")
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

captured_request = {}
def _fake_urlopen_ok(req, timeout=None):
    captured_request["url"] = req.full_url
    captured_request["method"] = req.get_method()
    captured_request["body"] = json.loads(req.data.decode("utf-8"))
    captured_request["timeout"] = timeout
    return _FakeHTTPResponse({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

real_urlopen = embeddings_backend.urllib.request.urlopen
real_enabled = embeddings_backend.REAL_EMBEDDINGS_AVAILABLE
embeddings_backend.REAL_EMBEDDINGS_AVAILABLE = True
embeddings_backend.urllib.request.urlopen = _fake_urlopen_ok
try:
    vectors = embeddings_backend.get_embeddings(["text A", "text B"])
    check("11.2b calls Ollama's real /api/embed path", captured_request["url"].endswith("/api/embed"), captured_request["url"])
    check("11.2b POSTs (not GETs)", captured_request["method"] == "POST", captured_request["method"])
    check("11.2b request body matches Ollama's documented shape", captured_request["body"] == {"model": embeddings_backend.OLLAMA_EMBED_MODEL, "input": ["text A", "text B"]}, captured_request["body"])
    check("11.2b uses a short timeout so a dead daemon can't hang a live demo", 0 < captured_request["timeout"] <= 10, captured_request["timeout"])
    check("11.2b parses the real 'embeddings' response key correctly", vectors == [[0.1, 0.2], [0.3, 0.4]], vectors)
finally:
    embeddings_backend.urllib.request.urlopen = real_urlopen
    embeddings_backend.REAL_EMBEDDINGS_AVAILABLE = real_enabled

# --- 11.2c a malformed response (wrong vector count) raises rather than silently mismatching ---
def _fake_urlopen_short(req, timeout=None):
    return _FakeHTTPResponse({"embeddings": [[0.1, 0.2]]})  # asked for 2 texts, got 1 back

embeddings_backend.REAL_EMBEDDINGS_AVAILABLE = True
embeddings_backend.urllib.request.urlopen = _fake_urlopen_short
try:
    raised_short = False
    try:
        embeddings_backend.get_embeddings(["text A", "text B"])
    except RuntimeError:
        raised_short = True
    check("11.2c a response with the wrong vector count raises instead of mismatching silently", raised_short)
finally:
    embeddings_backend.urllib.request.urlopen = real_urlopen
    embeddings_backend.REAL_EMBEDDINGS_AVAILABLE = real_enabled

# --- 11.3 _real_embedding_similarities returns None (triggers TF-IDF fallback) when not opted in ---
sims = agent2._real_embedding_similarities("some new project text", ["some existing project text"])
check("11.3 _real_embedding_similarities returns None with the flag unset", sims is None, sims)

# --- 11.4 find_closest_match still works end-to-end via the TF-IDF fallback (unchanged behavior) ---
existing = [p for p in projects if p.status in ("accepted", "in_progress", "completed")][:5]
target = by_id["SUB-0001"]
match, score = agent2.find_closest_match(target, existing)
check("11.4 find_closest_match returns a real result via TF-IDF fallback", match is not None and 0.0 <= score <= 1.0, (match.project_id if match else None, score))

# --- 11.5 monkeypatched real-embeddings path: correct match selection when a key IS present ---
class FakeEmbeddingsBackend:
    """Deterministic fake: encodes each text as a one-hot-ish vector based on a keyword, so the
    'closest' vector is unambiguous and NOT the same project TF-IDF would pick (proves the real
    path, not TF-IDF, is what actually ran)."""
    REAL_EMBEDDINGS_AVAILABLE = True
    def __init__(self):
        self.calls = []
    def get_embeddings(self, texts):
        self.calls.append(texts)
        out = []
        for t in texts:
            if "UNIQUE_MARKER_MATCH" in t:
                out.append([1.0, 0.0, 0.0])
            elif "totally different filler" in t:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.99, 0.01, 0.0])  # close to the marker vector
        return out

fake_new = type("P", (), {"objective": "UNIQUE_MARKER_MATCH project", "project_name": "New", "solution": "x", "project_id": None})()
fake_match = type("P", (), {"objective": "UNIQUE_MARKER_MATCH sibling project", "project_name": "Match", "solution": "y", "project_id": "PRJ-FAKE-MATCH", "submission_id": "SUB-FAKE-MATCH"})()
fake_decoy = type("P", (), {"objective": "totally different filler content", "project_name": "Decoy", "solution": "z", "project_id": "PRJ-FAKE-DECOY", "submission_id": "SUB-FAKE-DECOY"})()

real_backend = agent2.embeddings_backend
fake = FakeEmbeddingsBackend()
agent2.embeddings_backend = fake
try:
    match2, score2 = agent2.find_closest_match(fake_new, [fake_decoy, fake_match])
    check("11.5 real-embeddings path is actually exercised (backend was called)", len(fake.calls) == 1, fake.calls)
    check("11.5 real-embeddings path picks the semantically closest project, not TF-IDF's pick", match2 is fake_match, getattr(match2, "project_id", None))
finally:
    agent2.embeddings_backend = real_backend

# --- 11.6 real-embeddings failure (e.g. network error) falls back to TF-IDF transparently ---
class FailingEmbeddingsBackend:
    REAL_EMBEDDINGS_AVAILABLE = True
    def get_embeddings(self, texts):
        raise ConnectionError("simulated network failure")

agent2.embeddings_backend = FailingEmbeddingsBackend()
try:
    match3, score3 = agent2.find_closest_match(target, existing)
    check("11.6 a failed real-embeddings call falls back to TF-IDF instead of crashing", match3 is not None, (match3.project_id if match3 else None, score3))
finally:
    agent2.embeddings_backend = real_backend

# --- 11.7 the default (unpatched) module is still wired correctly after all monkeypatching ---
check("11.7 agent2.embeddings_backend is restored to the real module", agent2.embeddings_backend is embeddings_backend)

# --- 11.8-11.10 Agent 1's deterministic fallback parser (unscripted-input resilience) ---
# Real submission-email shape, straight from scripts/demo_engine.py's SCENARIO_EMAILS (case 1) —
# deliberately NOT one of the pre-authored mock_response cases, to prove this is genuinely unscripted
# input being handled, not a fixture.
SAMPLE_EMAIL = (
    "From: Grace Lim <grace.lim@company.com>\n"
    "Subject: Proposal: Customer support AI triage\n\n"
    "Hi PMO team,\n\nI'd like to submit a proposal: Customer support AI triage.\n\n"
    "Objective: Customer support tickets take too long to triage and route.\n"
    "Proposed solution: An automated triage and routing layer built on existing ticketing data.\n\n"
    "Estimated business impact: $220,000. Estimated CAPEX: $60,000 (fully funded).\n"
    "Expected launch: October 2026.\n"
    "Risk: No significant risk identified at this stage.\n\n"
    "Team: Grace Lim, Daniel Ho — Sales, Southeast Asia.\n\nThanks,\nGrace"
)

fallback_result = _deterministic_fallback_parse(SAMPLE_EMAIL)
check("11.8 fallback parser extracts submitter_name from From:", fallback_result["submitter_name"] == "Grace Lim", fallback_result["submitter_name"])
check("11.8 fallback parser extracts objective", "triage and route" in (fallback_result["objective"] or ""), fallback_result["objective"])
check("11.8 fallback parser extracts solution", "automated triage" in (fallback_result["solution"] or ""), fallback_result["solution"])
check("11.8 fallback parser extracts business_impact_usd as a real number", fallback_result["business_impact_usd"] == 220000.0, fallback_result["business_impact_usd"])
check("11.8 fallback parser extracts capex_usd as a real number", fallback_result["capex_usd"] == 60000.0, fallback_result["capex_usd"])
check("11.8 fallback parser extracts team_members, dropping the dept/region suffix", fallback_result["team_members"] == ["Grace Lim", "Daniel Ho"], fallback_result["team_members"])

# --- 11.9 the previous behavior (crash) is gone: parse_intake() no longer raises with no mock_response ---
raised2 = False
try:
    out, dur = parse_intake(SAMPLE_EMAIL)  # no mock_response — this used to raise RuntimeError outright
except RuntimeError:
    raised2 = True
check("11.9 parse_intake() no longer crashes on unscripted input in MOCK_MODE", raised2 is False)
check("11.9 parse_intake() reaches pmo_review via the fallback parser (all 3 required fields present)", out["status"] == "pmo_review", out)
check("11.9 parse_intake() includes the full incomplete_fields audit", "incomplete_fields" in out and isinstance(out["incomplete_fields"], list), out.get("incomplete_fields"))

# --- 11.10 existing scripted-mock behavior is completely unchanged (regression guard) ---
from src.agents.agent1_intake_parser import PROJECT_001_EMAIL, PROJECT_001_MOCK_RESPONSE
out2, dur2 = parse_intake(PROJECT_001_EMAIL, mock_response=PROJECT_001_MOCK_RESPONSE)
check("11.10 a scripted mock_response still takes priority over the fallback parser", out2["status"] == "rejected" and out2["parsed_fields"] is PROJECT_001_MOCK_RESPONSE, out2["status"])

print()
passed = sum(1 for _, s in results if s == "PASS")
print(f"Phase 11: {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
