"""
State machine — §8. Manual Gates 1-3 cannot be skipped (§8.2 guardrail 3, hard-coded, not prompted).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.schemas import Status, ALLOWED_TRANSITIONS

class IllegalTransitionError(Exception):
    pass

def transition(current_status: str, target_status: str) -> str:
    cur = Status(current_status)
    tgt = Status(target_status)
    if tgt not in ALLOWED_TRANSITIONS.get(cur, set()):
        raise IllegalTransitionError(
            f"Illegal transition: {cur.value} -> {tgt.value}. "
            f"Allowed from {cur.value}: {[s.value for s in ALLOWED_TRANSITIONS.get(cur, set())]}"
        )
    return tgt.value

# §8.2 guardrail 3 — only Agent 7 may set status=accepted, and only immediately after Gate 2 = Accept
def accept_project(conn, submission_id, gate2_decision, agent="agent7_acceptance_handler"):
    if gate2_decision != "accept":
        raise PermissionError("Cannot set status=accepted without an immediately-prior Gate 2 = Accept decision.")
    from src.db.repositories import get_project, update_status
    p = get_project(conn, submission_id)
    if p is None:
        raise ValueError("Unknown project")
    new_status = transition(p["status"], Status.ACCEPTED.value)
    update_status(conn, submission_id, new_status)
    return new_status
