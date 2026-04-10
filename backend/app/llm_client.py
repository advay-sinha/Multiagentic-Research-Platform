from __future__ import annotations

import logging
import os
import time

import httpx

from .settings import load_settings

_logger = logging.getLogger("research_api")

# Retry config for transient errors (429 rate-limit, 503 overloaded)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5, 10]  # seconds between retries
_RETRYABLE_STATUS = {429, 503}


class LLMClient:
    def __init__(self) -> None:
        self._settings = load_settings()
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")

    def generate(self, prompt: str, user_content: str) -> str:
        provider = self._settings.llm_provider.lower()
        if provider == "gemini" and self._settings.gemini_api_key:
            return self._generate_gemini(prompt, user_content)
        if provider == "openai" and self._openai_api_key:
            return self._generate_openai(prompt, user_content)
        return self._stub(prompt, user_content)

    def _generate_gemini(self, prompt: str, user_content: str) -> str:
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

        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(url, json=payload)
                    if response.status_code in _RETRYABLE_STATUS:
                        wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        _logger.warning(
                            "Gemini API %s (attempt %d/%d) — retrying in %ds",
                            response.status_code, attempt + 1, _MAX_RETRIES, wait,
                        )
                        time.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                _logger.warning("Gemini API HTTP %s — falling back to stub", exc.response.status_code)
                return self._stub(prompt, user_content)
            except Exception as exc:
                last_exc = exc
                _logger.warning("Gemini API error (%s) — falling back to stub", exc)
                return self._stub(prompt, user_content)

        _logger.warning(
            "Gemini API failed after %d retries — falling back to stub (last: %s)",
            _MAX_RETRIES, last_exc or "retryable status",
        )
        return self._stub(prompt, user_content)

    def _generate_openai(self, prompt: str, user_content: str) -> str:
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._openai_api_key}"}
        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _stub(self, prompt: str, user_content: str) -> str:
        return f"[stub] {prompt} | {user_content[:200]}".strip()
