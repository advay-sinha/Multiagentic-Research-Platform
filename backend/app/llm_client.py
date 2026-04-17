from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .settings import load_settings

_logger = logging.getLogger("research_api")

_AUTH_FAILURE_STATUS = {401, 403, 404}


@dataclass
class ProviderState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_call_ts: float = 0.0
    cooldown_until_ts: float = 0.0


# Per-provider state. Each provider serializes its own calls, tracks cooldowns
# after rate limits, and can be skipped temporarily when known-unavailable.
_PROVIDER_STATE: dict[str, ProviderState] = {}


def _provider_state(provider: str) -> ProviderState:
    return _PROVIDER_STATE.setdefault(provider, ProviderState())


def _min_interval(provider: str) -> float:
    # Free-tier safe gaps (measured empirically 2026-04-16):
    #   Gemini     gemini-2.5-flash  10 RPM  → 6.5s  (6s nominal + buffer)
    #   OpenRouter :free aggregate   20 RPM  → 6.5s  (shared daily pool)
    #   OpenAI                                2.5s   (tier-1 has headroom)
    defaults = {"gemini": 6500, "openrouter": 6500, "openai": 2500}
    default = defaults.get(provider, 3000)
    key = f"LLM_MIN_INTERVAL_MS_{provider.upper()}"
    return float(os.environ.get(key) or os.environ.get("LLM_MIN_INTERVAL_MS") or default) / 1000.0


def _cooldown_seconds(provider: str, status_code: int, retry_after: Optional[str] = None) -> float:
    try:
        if retry_after:
            return max(float(retry_after), 0.0)
    except ValueError:
        pass

    defaults = {
        429: 90.0 if provider == "openrouter" else 60.0,
        503: 15.0,
        401: 300.0,
        403: 300.0,
        404: 300.0,
    }
    provider_key = f"LLM_COOLDOWN_SECONDS_{provider.upper()}_{status_code}"
    global_key = f"LLM_COOLDOWN_SECONDS_{status_code}"
    raw = os.environ.get(provider_key) or os.environ.get(global_key)
    return float(raw) if raw else defaults.get(status_code, 30.0)


def _mark_cooldown(provider: str, seconds: float) -> None:
    state = _provider_state(provider)
    cooldown_until = time.monotonic() + max(seconds, 0.0)
    with state.lock:
        state.cooldown_until_ts = max(state.cooldown_until_ts, cooldown_until)


def _cooldown_remaining(provider: str) -> float:
    state = _provider_state(provider)
    with state.lock:
        return max(state.cooldown_until_ts - time.monotonic(), 0.0)

def _parse_gemini_response(data: dict) -> Optional[str]:
    """Safely extract Gemini text. Returns None on safety block / empty response.

    Gemini returns 200 OK with either:
      - Normal: candidates[0].content.parts[0].text
      - Safety-blocked: candidates[0].finishReason='SAFETY', no parts
      - Rate-limited logically: no candidates, just promptFeedback
    None triggers failover to the next provider instead of crashing.
    """
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        _logger.warning("gemini returned no candidates (promptFeedback=%s)", feedback)
        return None
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        reason = candidates[0].get("finishReason")
        _logger.warning("gemini candidate had no parts (finishReason=%s)", reason)
        return None
    text = parts[0].get("text") or ""
    return text.strip() or None


def _throttle(provider: str) -> None:
    state = _provider_state(provider)
    with state.lock:
        now = time.monotonic()
        wait = (state.last_call_ts + _min_interval(provider)) - now
        if wait > 0:
            time.sleep(wait)
        state.last_call_ts = time.monotonic()


class LLMClient:
    def __init__(self) -> None:
        self._settings = load_settings()
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        # Flipped to True once any generate() call falls through to the stub
        # (all providers rate-limited or misconfigured). Graph nodes can inspect
        # this to short-circuit the writer/critic/verifier loop instead of
        # hammering providers that are already in cooldown.
        self.stub_fallback_hit = False

    def _has_creds(self, provider: str) -> bool:
        if provider == "gemini":
            return bool(self._settings.gemini_api_key)
        if provider == "openrouter":
            return bool(self._settings.openrouter_api_key)
        if provider == "openai":
            return bool(self._openai_api_key)
        return False

    def _primary_for(self, agent: Optional[str]) -> str:
        mapped = None
        if agent:
            mapped = self._settings.agent_provider_map.get(agent.lower())
        return (mapped or self._settings.llm_provider or "gemini").lower()

    def _fallback_chain(self, agent: Optional[str]) -> list[str]:
        """Ordered providers to try for this agent: primary first, then the
        other configured provider, dedup'd, creds-only.

        OpenAI is intentionally excluded — no key available in this deployment.
        """
        primary = self._primary_for(agent)
        if primary == "openai":
            primary = "gemini"
        order = [primary] + [p for p in ("gemini", "openrouter") if p != primary]
        return [p for p in order if self._has_creds(p)]

    def generate(self, prompt: str, user_content: str, agent: Optional[str] = None) -> str:
        chain = self._fallback_chain(agent)
        if not chain:
            _logger.warning("No providers with credentials configured — returning stub")
            self.stub_fallback_hit = True
            return self._stub(prompt, user_content)
        for provider in chain:
            remaining = _cooldown_remaining(provider)
            if remaining > 0:
                _logger.info(
                    "Skipping provider %s for agent=%s — cooldown active for %.1fs",
                    provider, agent, remaining,
                )
                continue
            _throttle(provider)
            result = self._dispatch(provider, prompt, user_content)
            if result is not None:
                return result
            _logger.warning("Provider %s failed for agent=%s — trying next", provider, agent)
        self.stub_fallback_hit = True
        return self._stub(prompt, user_content)

    def _dispatch(self, provider: str, prompt: str, user_content: str) -> Optional[str]:
        if provider == "gemini":
            return self._generate_gemini(prompt, user_content)
        if provider == "openrouter":
            return self._generate_openrouter(prompt, user_content)
        if provider == "openai":
            return self._generate_openai(prompt, user_content)
        return None

    def _generate_gemini(self, prompt: str, user_content: str) -> Optional[str]:
        model = self._settings.gemini_model
        model_id = model if model.startswith("models/") else f"models/{model}"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/{model_id}"
            f":generateContent?key={self._settings.gemini_api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": prompt}]},
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {"temperature": 0.2},
        }
        return self._post_with_retry(
            url, payload, headers=None, provider="gemini",
            parse=_parse_gemini_response,
        )

    def _generate_openrouter(self, prompt: str, user_content: str) -> Optional[str]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": self._settings.openrouter_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER") or "http://localhost:3000",
            "X-Title": "Multiagentic Research Platform",
        }
        return self._post_with_retry(
            url, payload, headers=headers, provider="openrouter",
            parse=lambda d: d["choices"][0]["message"]["content"].strip(),
        )

    def _generate_openai(self, prompt: str, user_content: str) -> Optional[str]:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._openai_api_key}"}
        return self._post_with_retry(
            url, payload, headers=headers, provider="openai",
            parse=lambda d: d["choices"][0]["message"]["content"].strip(),
        )

    def _post_with_retry(self, url, payload, headers, provider, parse) -> Optional[str]:
        # Treat 429 as a cooldown signal, not something to hammer synchronously.
        # Retry only transient 503s inline; 429/401/403/404 temporarily take the
        # provider out of rotation so later agents do not re-hit it immediately.
        max_retries = 1
        backoff = [3, 8]

        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(url, json=payload, headers=headers)
                    if response.status_code == 429:
                        wait = _cooldown_seconds(provider, 429, response.headers.get("Retry-After"))
                        _mark_cooldown(provider, wait)
                        _logger.warning(
                            "%s 429 — entering cooldown for %.1fs and failing over",
                            provider, wait,
                        )
                        return None
                    if response.status_code == 503:
                        if attempt >= max_retries:
                            wait = _cooldown_seconds(provider, 503, response.headers.get("Retry-After"))
                            _mark_cooldown(provider, wait)
                            _logger.warning(
                                "%s 503 — max retries reached, cooldown %.1fs, failing over",
                                provider, wait,
                            )
                            return None
                        retry_after = response.headers.get("Retry-After")
                        try:
                            wait = float(retry_after) if retry_after else backoff[min(attempt, len(backoff) - 1)]
                        except ValueError:
                            wait = backoff[min(attempt, len(backoff) - 1)]
                        _logger.warning(
                            "%s 503 (attempt %d/%d) — retry in %.1fs",
                            provider, attempt + 1, max_retries + 1, wait,
                        )
                        time.sleep(wait)
                        continue
                    if response.status_code in _AUTH_FAILURE_STATUS:
                        wait = _cooldown_seconds(provider, response.status_code)
                        _mark_cooldown(provider, wait)
                        _logger.error(
                            "%s %s — provider disabled for %.1fs. Check credentials/model configuration.",
                            provider, response.status_code, wait,
                        )
                        return None
                    response.raise_for_status()
                    try:
                        parsed = parse(response.json())
                    except Exception as exc:
                        body = response.text[:300] if response.text else "<empty>"
                        _logger.warning("%s parse failed (%s) — body=%s", provider, exc, body)
                        return None
                    if parsed is None or not str(parsed).strip():
                        _logger.warning("%s returned empty content — failing over", provider)
                        return None
                    return parsed
            except httpx.HTTPStatusError as exc:
                _logger.warning("%s HTTP %s — failing over", provider, exc.response.status_code)
                return None
            except Exception as exc:
                _logger.warning("%s error (%s) — failing over", provider, exc)
                return None
        return None

    def _stub(self, prompt: str, user_content: str) -> str:
        return f"[stub] {prompt} | {user_content[:200]}".strip()
