"""
Real embeddings backend for Agent 2 (§4/§16) — "comparing Foo's repo" upversion, see
docs/comparing-foos-repo.md for the full comparison and rollback plan this came out of.

Backend: Ollama (local daemon) — matching a teammate's repo (THENGFY/Transform-Office-Workflow)
choice directly this time. An earlier version of this module used Voyage AI's hosted API instead,
specifically to avoid a local-daemon dependency (see docs/comparing-foos-repo.md's original
reasoning). Revised after further discussion: the user explicitly chose to accept that dependency
in exchange for zero API cost and zero network calls at inference time, on the condition that
TF-IDF is the backup if Ollama isn't responding — which this module was already built to guarantee
regardless of which real backend sits behind it (see agent2_duplicate_checker.py's
_real_embedding_similarities(), unchanged by this swap: it catches ANY failure from get_embeddings()
below and falls back to TF-IDF).

Opt-in via USE_OLLAMA_EMBEDDINGS=1 — not "is Ollama installed", since there's no way to know that
without attempting a real call. Absent the flag (the default), this module is never even reached,
so the demo and the full test suite stay fast, deterministic, and fully network-independent exactly
as before. Only someone who has actually started `ollama serve` opts in. A short timeout
(OLLAMA_TIMEOUT_SECONDS) keeps a live demo from hanging if the daemon is up but unresponsive.

Implemented with stdlib `urllib.request` only — no new pip dependency, matching src/llm/client.py's
Anthropic path and this module's own earlier Voyage version.

Not independently verified end-to-end against a real running Ollama instance — this sandbox's
network allowlist blocks ollama.com, so the Ollama binary/model couldn't be installed here. Verified
instead via careful reading of Ollama's own /api/embed docs (docs.ollama.com/capabilities/embeddings)
and thorough monkeypatched tests (tests/scenarios/test_phase11.py) exercising the real request/
response shape and every failure path. The first real run needs to happen on a machine with Ollama
actually installed — see README.md's Mock mode section for the exact steps.
"""
import os, json, urllib.request, urllib.error


def _truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


OLLAMA_ENABLED = _truthy(os.environ.get("USE_OLLAMA_EMBEDDINGS"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "all-minilm")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "3"))

# Same external name every caller (agent2_duplicate_checker.py) already relies on — this swap
# changes the backend behind it, not the interface. Here it means "opted in via env var", not
# "confirmed reachable": reachability can only be proven by actually attempting a call, which is
# exactly what get_embeddings() does below — a dead daemon still degrades to TF-IDF via the
# caller's existing try/except, unchanged by this swap.
REAL_EMBEDDINGS_AVAILABLE = OLLAMA_ENABLED

_ENDPOINT = f"{OLLAMA_HOST}/api/embed"


def get_embeddings(texts: list) -> list:
    """Real call only — raises on any failure (not opted in, daemon unreachable, timed out, model
    not pulled, malformed response). Callers (agent2_duplicate_checker.find_closest_match) are
    responsible for catching and falling back to TF-IDF; this function never silently returns a
    fake vector."""
    if not REAL_EMBEDDINGS_AVAILABLE:
        raise RuntimeError("USE_OLLAMA_EMBEDDINGS not set — no real embeddings backend available.")
    payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        _ENDPOINT, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    embeddings = body.get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        # A short/malformed response is just as unusable as a network failure — raise so the
        # caller falls back, rather than silently pairing the wrong vector with the wrong project.
        got = len(embeddings) if embeddings else 0
        raise RuntimeError(f"Ollama returned {got} embeddings for {len(texts)} inputs — expected one each.")
    return embeddings
