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
    openrouter_api_key: str
    openrouter_model: str
    cors_allow_origin: str
    max_agent_iterations: int
    agent_provider_map: dict
    retrieval_mode: str


def _load_agent_provider_map() -> dict:
    # Default split: alternate providers to avoid rate-limit clustering.
    # Planner→gemini, Writer→openrouter, Critic→gemini, Verifier→openrouter.
    defaults = {
        "planner": "gemini",
        "writer": "openrouter",
        "critic": "gemini",
        "verifier": "openrouter",
    }
    raw = os.environ.get("AGENT_PROVIDER_MAP") or ""
    if raw:
        for pair in raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                defaults[k.strip().lower()] = v.strip().lower()
    return defaults


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL") or ""
    embedding_model = os.environ.get("EMBEDDING_MODEL") or "models/gemini-embedding-002"
    embedding_dim = int(os.environ.get("EMBEDDING_DIM") or "768")
    llm_provider = os.environ.get("LLM_PROVIDER") or "gemini"
    openai_model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    gemini_api_key = os.environ.get("GEMINI_API_KEY") or ""
    gemini_model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY") or ""
    openrouter_model = os.environ.get("OPENROUTER_MODEL") or "openai/gpt-oss-120b:free"
    cors_allow_origin = os.environ.get("CORS_ALLOW_ORIGIN") or "http://localhost:3000"
    # Single-pass by default. Each iteration = writer+critic+verifier (3 LLM
    # calls). 5 iterations × 3 + planner = up to 16 calls/query, which blows
    # past free-tier RPM limits. Override via env if you have paid tier.
    max_agent_iterations = int(os.environ.get("MAX_AGENT_ITERATIONS") or "1")
    # Retrieval strategy:
    #   hybrid    — web search + embed+index to pgvector + vector search (heavy embed use)
    #   web_only  — web search, use extracted text directly as evidence (zero embed calls)
    #   vector_only — skip web, only search pgvector
    #   off       — no retrieval (LLM-only)
    retrieval_mode = (os.environ.get("RETRIEVAL_MODE") or "web_only").strip().lower()
    if retrieval_mode not in {"hybrid", "web_only", "vector_only", "off"}:
        retrieval_mode = "web_only"
    return Settings(
        database_url=database_url,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        llm_provider=llm_provider,
        openai_model=openai_model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        cors_allow_origin=cors_allow_origin,
        max_agent_iterations=max_agent_iterations,
        agent_provider_map=_load_agent_provider_map(),
        retrieval_mode=retrieval_mode,
    )
