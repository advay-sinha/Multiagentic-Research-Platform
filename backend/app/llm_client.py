from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class LLMSettings:
    provider: str
    api_key: Optional[str]
    model: str


def _load_settings() -> LLMSettings:
    provider = os.environ.get("LLM_PROVIDER", "stub")
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return LLMSettings(provider=provider, api_key=api_key, model=model)


class LLMClient:
    def __init__(self) -> None:
        self._settings = _load_settings()

    def generate(self, prompt: str, user_content: str) -> str:
        if self._settings.provider.lower() == "openai" and self._settings.api_key:
            return self._generate_openai(prompt, user_content)
        return self._stub(prompt, user_content)

    def _generate_openai(self, prompt: str, user_content: str) -> str:
        payload = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}
        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _stub(self, prompt: str, user_content: str) -> str:
        return f"[stub] {prompt} | {user_content[:200]}".strip()
