from __future__ import annotations

import os

import httpx

from .settings import load_settings


class LLMClient:
    def __init__(self) -> None:
        self._settings = load_settings()
        self._api_key = os.environ.get("OPENAI_API_KEY")

    def generate(self, prompt: str, user_content: str) -> str:
        if self._settings.llm_provider.lower() == "openai" and self._api_key:
            return self._generate_openai(prompt, user_content)
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
        headers = {"Authorization": f"Bearer {self._api_key}"}
        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _stub(self, prompt: str, user_content: str) -> str:
        return f"[stub] {prompt} | {user_content[:200]}".strip()
