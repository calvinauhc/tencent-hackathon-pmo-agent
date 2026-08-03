"""
LLM client wrapper — §16 model routing.
Real mode: calls Anthropic API if ANTHROPIC_API_KEY is set (used when porting/testing with a live key).
Mock mode: deterministic canned responses, so the full pipeline is testable end to end with zero credits
and zero network dependency — this is how Phase 1-3 are verified in this build.
"""
import os, json

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MOCK_MODE = API_KEY is None

_client = None
if not MOCK_MODE:
    import anthropic
    _client = anthropic.Anthropic(api_key=API_KEY)

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
}

class LLMCall:
    """Records every call for audit_log wiring (§2.5) regardless of mock/real mode."""
    def __init__(self):
        self.log = []

    def call(self, agent_name: str, model_tier: str, system: str, user: str, mock_response=None):
        import time
        start = time.time()
        if MOCK_MODE:
            if mock_response is None:
                raise RuntimeError(
                    f"MOCK_MODE active (no ANTHROPIC_API_KEY) and agent '{agent_name}' called "
                    f"without a mock_response. Provide one for tests, or set ANTHROPIC_API_KEY for real calls."
                )
            result = mock_response
        else:
            resp = _client.messages.create(
                model=MODEL_MAP[model_tier],
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = resp.content[0].text
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = {"raw_text": text}
        duration_ms = int((time.time() - start) * 1000)
        self.log.append({
            "agent": agent_name, "model_tier": model_tier, "mock": MOCK_MODE,
            "duration_ms": duration_ms,
        })
        return result, duration_ms

llm = LLMCall()
