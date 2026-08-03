"""
Agent 2 — Duplicate Checker. §2, §4.
Similarity: local TF-IDF + cosine as a demo-scope stand-in for real embeddings/pgvector (§4, §16) —
swap for a real embedding model + kb_documents-style vector column when porting to CodeBuddy.
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
from src.knowledge.opl_loader import load_opl

def _text_of(project) -> str:
    base = " ".join(filter(None, [project.objective, project.project_name, project.solution]))
    opl_text = load_opl(getattr(project, "project_id", None))
    return f"{base} {opl_text}".strip() if opl_text else base

def find_closest_match(new_project, existing_projects):
    """Returns (best_match_project, similarity_score) or (None, 0.0) if no existing projects."""
    corpus = [_text_of(new_project)] + [_text_of(p) for p in existing_projects]
    if not existing_projects or not corpus[0].strip():
        return None, 0.0
    vect = TfidfVectorizer().fit_transform(corpus)
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
