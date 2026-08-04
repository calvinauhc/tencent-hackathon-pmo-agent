"""
Real embeddings backend for Agent 2 (§4/§16) — "comparing Foo's repo" upversion, see
docs/comparing-foos-repo.md for the full comparison and rollback plan this came out of.

Opt-in via VOYAGE_API_KEY, mirroring src/llm/client.py's MOCK_MODE pattern exactly: absent a key,
Agent 2 keeps using its existing TF-IDF + cosine stand-in (unchanged — every existing test still
exercises exactly that path, untouched). This module is purely additive; nothing calls it unless
REAL_EMBEDDINGS_AVAILABLE is True, and even then agent2_duplicate_checker.py falls back to TF-IDF
if a real call fails for any reason (network, bad key, rate limit) rather than raising.

Provider choice — Voyage AI, not Ollama or sentence-transformers:
A teammate's repo (THENGFY/Transform-Office-Workflow) uses Ollama (local nomic-embed-text) + Chroma
for this exact problem — free and offline, genuinely worth knowing about. Deliberately not copied
as-is here: Ollama requires a local daemon + downloaded model weights present on whatever machine
actually runs the demo, which this build has no way to guarantee (§0's "one script, no external
services" demo-reliability property would be broken). sentence-transformers avoids the daemon but
pulls in PyTorch + model weights — a large, slow local install, not something to add silently this
close to a submission deadline. Voyage AI is Anthropic's own recommended embeddings partner
(docs.anthropic.com), reachable with a plain HTTPS call — the exact same category of trade-off
already accepted for the real LLM tier (network + a key required when enabled), not a new one.

Implemented with stdlib `urllib.request` only — no new pip dependency. requirements.txt still just
needs scikit-learn + anthropic.
"""
import os, json, urllib.request, urllib.error

VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY")
REAL_EMBEDDINGS_AVAILABLE = VOYAGE_API_KEY is not None

EMBED_MODEL = "voyage-3-lite"
_ENDPOINT = "https://api.voyageai.com/v1/embeddings"


def get_embeddings(texts: list) -> list:
    """Real call only — raises on any failure (no key, network error, bad response). Callers
    (agent2_duplicate_checker.find_closest_match) are responsible for catching and falling back to
    TF-IDF; this function never silently returns a fake vector."""
    if not REAL_EMBEDDINGS_AVAILABLE:
        raise RuntimeError("VOYAGE_API_KEY not set — no real embeddings backend available.")
    payload = json.dumps({"input": texts, "model": EMBED_MODEL}).encode("utf-8")
    req = urllib.request.Request(
        _ENDPOINT, data=payload, method="POST",
        headers={"Authorization": f"Bearer {VOYAGE_API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    # Voyage returns `data` in the same order as `input`, each with an `index` — sort defensively
    # rather than trusting response order, since a caller mismatching texts to vectors would be a
    # silent, hard-to-notice bug (wrong project flagged as the closest match).
    ordered = sorted(body["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in ordered]
