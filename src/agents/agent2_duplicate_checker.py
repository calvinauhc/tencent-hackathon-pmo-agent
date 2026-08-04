"""
Agent 2 — Duplicate Checker. §2, §4.
Similarity: local TF-IDF + cosine as the default, demo-scope stand-in for real embeddings/pgvector
(§4, §16) — this is still what every existing test exercises and still what runs with zero setup.

Optional real-embeddings upgrade ("comparing Foo's repo", docs/comparing-foos-repo.md): if
USE_OLLAMA_EMBEDDINGS=1 is set, find_closest_match() tries a real local Ollama embedding call first
and only falls back to TF-IDF if that call fails for any reason (daemon not running, timed out,
model not pulled) — never raises past this function. Absent the flag (the default), behavior is
byte-for-byte identical to before this upgrade. (An earlier version of this upgrade used a hosted
API — Voyage AI — instead of Ollama; see src/llm/embeddings.py's docstring for why it was swapped.)

Only the borderline band (0.65-0.85) calls an LLM (Sonnet, §16) for adjudication.

§7.2.4 extends the corpus text for a *completed* project to include its published OPL (§7.2.3), not
just its original terse objective/solution fields — catches a new submission that closely resembles
a past project's fuller retrospective description, even one that reads differently from how it was
originally pitched at intake.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.shared.config import DUPLICATE_AUTO_FLAG_THRESHOLD, DUPLICATE_NOT_DUPLICATE_THRESHOLD
from src.llm.client import llm
from src.llm import embeddings as embeddings_backend
from src.knowledge.opl_loader import load_opl

def _text_of(project) -> str:
    base = " ".join(filter(None, [project.objective, project.project_name, project.solution]))
    opl_text = load_opl(getattr(project, "project_id", None))
    return f"{base} {opl_text}".strip() if opl_text else base

def _real_embedding_similarities(new_text, existing_texts):
    """Returns a similarity array (same shape/semantics as the TF-IDF path) using real Voyage
    embeddings, or None if the real backend isn't available/fails. Isolated in its own function so
    find_closest_match's fallback logic stays simple to read."""
    if not embeddings_backend.REAL_EMBEDDINGS_AVAILABLE:
        return None
    try:
        vectors = embeddings_backend.get_embeddings([new_text] + existing_texts)
    except Exception as e:
        # Network hiccup, bad/revoked key, rate limit — never let a real-embeddings failure take
        # down duplicate checking. Fall back to TF-IDF exactly as if no key had been set.
        print(f"[Agent2 Warning] Real embeddings call failed: {e}. Falling back to TF-IDF.")
        return None
    sims = cosine_similarity([vectors[0]], vectors[1:]).flatten()
    return sims

def find_closest_match(new_project, existing_projects):
    """Returns (best_match_project, similarity_score) or (None, 0.0) if no existing projects."""
    if not existing_projects:
        return None, 0.0
    new_text = _text_of(new_project)
    if not new_text.strip():
        return None, 0.0
    existing_texts = [_text_of(p) for p in existing_projects]

    sims = _real_embedding_similarities(new_text, existing_texts)
    if sims is None:
        vect = TfidfVectorizer().fit_transform([new_text] + existing_texts)
        sims = cosine_similarity(vect[0:1], vect[1:]).flatten()

    best_idx = sims.argmax()
    return existing_projects[best_idx], float(sims[best_idx])

ADJUDICATION_SYSTEM_PROMPT = (
    "Two project submissions have moderate text similarity. Read both in full and decide: are "
    "they genuinely the same underlying project (same pain point and same proposed solution), "
    "or are they different projects that happen to use similar words? Return a reasoned verdict."
)

def check_duplicate(new_project, existing_projects, mock_response=None):
    match, score = find_closest_match(new_project, existing_projects)
    if match is None:
        return {"verdict": "not_duplicate", "similarity": 0.0, "match": None}, 0

    if score >= DUPLICATE_AUTO_FLAG_THRESHOLD:
        return {"verdict": "duplicate", "similarity": score, "match": match.project_id or match.submission_id}, 0

    if score < DUPLICATE_NOT_DUPLICATE_THRESHOLD:
        return {"verdict": "not_duplicate", "similarity": score, "match": None}, 0

    # borderline band -> LLM adjudication
    user = (
        f"Submission A:\nObjective: {new_project.objective}\nSolution: {new_project.solution}\n\n"
        f"Submission B:\nObjective: {match.objective}\nSolution: {match.solution}"
    )
    result, duration_ms = llm.call(
        agent_name="agent2_borderline_adjudication", model_tier="sonnet",
        system=ADJUDICATION_SYSTEM_PROMPT, user=user, mock_response=mock_response,
    )
    verdict = "duplicate" if result.get("same_project") else "not_duplicate"
    return {"verdict": verdict, "similarity": score, "match": match.project_id or match.submission_id,
            "adjudication_rationale": result.get("rationale")}, duration_ms
