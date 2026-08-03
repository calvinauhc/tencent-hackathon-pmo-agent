"""
Agent 8 — Rejection Feedback Composer. §2, §11. Haiku tier (§16), draft + a distinct tone-check pass
(§8.2 closing note) — same self-review pattern as elsewhere in this build, not a rerun of the draft prompt.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.llm.client import llm
from src.notifications.templates import rejection_feedback

TONE_CHECK_SYSTEM = (
    "Review this rejection message. Does it contain accusatory language toward the requester, "
    "or does it read as constructive and actionable? Answer with a verdict and, if not constructive, "
    "a rewritten version."
)

def compose_rejection(project_name, reason, pmo_comment="", mock_tone_response=None):
    draft = rejection_feedback(project_name, reason, pmo_comment)
    tone_result, duration_ms = llm.call(
        agent_name="agent8_tone_check", model_tier="haiku",
        system=TONE_CHECK_SYSTEM, user=draft["body"],
        mock_response=mock_tone_response or {"constructive": True},
    )
    if not tone_result.get("constructive", True) and tone_result.get("rewritten"):
        draft["body"] = tone_result["rewritten"]
    return draft, duration_ms
