from __future__ import annotations

from typing import Any

import pytest

from backend.app import llm_client
from backend.app.llm_client import LLMClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responder) -> None:
        self._responder = responder

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url, json=None, headers=None):
        return self._responder(url, json, headers)


@pytest.fixture(autouse=True)
def reset_llm_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_client._PROVIDER_STATE.clear()
    monkeypatch.setenv("LLM_MIN_INTERVAL_MS", "0")
    monkeypatch.delenv("LLM_COOLDOWN_SECONDS_429", raising=False)
    monkeypatch.delenv("LLM_COOLDOWN_SECONDS_OPENROUTER_429", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_rate_limited_provider_enters_cooldown_and_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")

    calls = {"gemini": 0}

    def responder(url, payload, headers):
        calls["gemini"] += 1
        return FakeResponse(429, {"error": {"message": "rate limited"}}, headers={"Retry-After": "120"})

    monkeypatch.setattr(llm_client.httpx, "Client", lambda timeout=60.0: FakeClient(responder))

    client = LLMClient()

    assert client.generate("prompt", "user text", agent="planner").startswith("[stub]")
    assert calls["gemini"] == 1

    assert client.generate("prompt", "user text", agent="planner").startswith("[stub]")
    assert calls["gemini"] == 1


def test_generate_falls_over_to_secondary_and_skips_cooled_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter-test")
    monkeypatch.setenv("AGENT_PROVIDER_MAP", "writer=openrouter")

    calls = {"openrouter": 0, "gemini": 0}

    def responder(url, payload, headers):
        if "openrouter.ai" in url:
            calls["openrouter"] += 1
            return FakeResponse(429, {"error": {"message": "rate limited"}}, headers={"Retry-After": "120"})
        calls["gemini"] += 1
        return FakeResponse(
            200,
            {
                "candidates": [
                    {"content": {"parts": [{"text": "Paris is the capital of France."}]}}
                ]
            },
        )

    monkeypatch.setattr(llm_client.httpx, "Client", lambda timeout=60.0: FakeClient(responder))

    client = LLMClient()

    first = client.generate("prompt", "user text", agent="writer")
    assert "paris" in first.lower()
    assert calls == {"openrouter": 1, "gemini": 1}

    second = client.generate("prompt", "user text", agent="writer")
    assert "paris" in second.lower()
    assert calls == {"openrouter": 1, "gemini": 2}
