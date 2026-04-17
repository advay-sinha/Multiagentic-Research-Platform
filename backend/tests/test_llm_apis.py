"""Live smoke tests for LLM providers.

Run with a populated .env to verify real API connectivity:
    pytest backend/tests/test_llm_apis.py -v -s

Tests skip when credentials are missing so CI stays green.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Support running this file directly via `python backend/tests/test_llm_apis.py`
# in addition to `pytest backend/tests/test_llm_apis.py`.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from backend.app.llm_client import LLMClient  # noqa: E402

SAMPLE_PROMPT = "Answer in one short sentence. No preamble."
SAMPLE_QUERY = "What is the capital of France?"


def _has_gemini() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _has_openrouter() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _is_real_output(text: str) -> bool:
    """Reject stub fallback and empty responses."""
    return bool(text) and not text.startswith("[stub]")


@pytest.fixture(scope="module")
def client() -> LLMClient:
    return LLMClient()


@pytest.mark.skipif(not _has_gemini(), reason="GEMINI_API_KEY not set")
def test_gemini_direct(client: LLMClient) -> None:
    out = client._generate_gemini(SAMPLE_PROMPT, SAMPLE_QUERY)
    if out is None:
        pytest.skip("Gemini rate-limited or unavailable")
    assert "paris" in out.lower(), f"Unexpected Gemini output: {out!r}"


@pytest.mark.skipif(not _has_openrouter(), reason="OPENROUTER_API_KEY not set")
def test_openrouter_direct(client: LLMClient) -> None:
    out = client._generate_openrouter(SAMPLE_PROMPT, SAMPLE_QUERY)
    if out is None:
        pytest.skip("OpenRouter rate-limited or unavailable — fallback chain still covers this")
    assert "paris" in out.lower(), f"Unexpected OpenRouter output: {out!r}"


@pytest.mark.skipif(not (_has_gemini() or _has_openrouter()), reason="No LLM creds set")
@pytest.mark.parametrize("agent", ["planner", "writer", "critic", "verifier"])
def test_agent_routing(client: LLMClient, agent: str) -> None:
    """Each agent should produce real output via its mapped provider or fallback."""
    out = client.generate(SAMPLE_PROMPT, SAMPLE_QUERY, agent=agent)
    if not _is_real_output(out):
        pytest.skip(f"Agent {agent} exhausted live providers and fell back to stub")
    assert "paris" in out.lower(), f"Agent {agent} unexpected output: {out!r}"


@pytest.mark.skipif(not (_has_gemini() or _has_openrouter()), reason="No LLM creds set")
def test_fallback_chain_order(client: LLMClient) -> None:
    """Planner primary=gemini; chain should list gemini before openrouter."""
    chain = client._fallback_chain("planner")
    assert chain, "Empty fallback chain — no providers have credentials"
    if _has_gemini() and _has_openrouter():
        assert chain[0] == "gemini"
        assert "openrouter" in chain


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
