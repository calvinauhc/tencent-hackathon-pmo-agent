"""
Iteration guard — §8.1. Caps reasoning turns/retries; fail-closed escalation to Manual Gate,
never a silent guess or infinite loop.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.config import MAX_REASONING_TURNS, MAX_RETRIES

class EscalatedToManualGate(Exception):
    """Raised (not silently swallowed) when an agent hits its cap — caller must route to a human."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)

def run_bounded(fn, *args, max_turns=MAX_REASONING_TURNS, max_retries=MAX_RETRIES, **kwargs):
    turns = 0
    retries = 0
    last_error = None
    while turns < max_turns:
        turns += 1
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            retries += 1
            if retries > max_retries:
                raise EscalatedToManualGate(
                    f"needs human review — automated check inconclusive after {retries} retries: {last_error}"
                )
    raise EscalatedToManualGate(
        f"needs human review — automated check inconclusive after {turns} reasoning turns"
    )
