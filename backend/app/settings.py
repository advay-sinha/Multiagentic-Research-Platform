from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    database_url: str
    embedding_model: str
    embedding_dim: int
    llm_provider: str
    openai_model: str
    gemini_api_key: str
    gemini_model: str
    cors_allow_origin: str
    max_agent_iterations: int


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL") or ""
    embedding_model = os.environ.get("EMBEDDING_MODEL") or "models/gemini-embedding-001"
    embedding_dim = int(os.environ.get("EMBEDDING_DIM") or "768")
    llm_provider = os.environ.get("LLM_PROVIDER") or "gemini"
    openai_model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    gemini_api_key = os.environ.get("GEMINI_API_KEY") or ""
    gemini_model = os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash"
    cors_allow_origin = os.environ.get("CORS_ALLOW_ORIGIN") or "http://localhost:3000"
    max_agent_iterations = int(os.environ.get("MAX_AGENT_ITERATIONS") or "5")
    return Settings(
        database_url=database_url,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        llm_provider=llm_provider,
        openai_model=openai_model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        cors_allow_origin=cors_allow_origin,
        max_agent_iterations=max_agent_iterations,
    )
