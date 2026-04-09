from __future__ import annotations

import logging
from typing import List

import httpx

from .settings import load_settings

_logger = logging.getLogger("research_api")


def embed_texts(texts: List[str]) -> List[List[float]]:
    settings = load_settings()
    if settings.gemini_api_key:
        return _embed_gemini(texts, settings.embedding_model, settings.gemini_api_key)
    raise RuntimeError(
        "No embedding provider configured. Set GEMINI_API_KEY in your environment."
    )


def _embed_gemini(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    """Embed texts using Gemini batchEmbedContents (single request), with per-text fallback."""
    model_id = model if model.startswith("models/") else f"models/{model}"

    # Try batch endpoint first (one HTTP call for all texts)
    try:
        return _embed_gemini_batch(texts, model_id, api_key)
    except Exception:
        _logger.warning("Batch embedding failed, falling back to individual calls")

    # Fallback: one call per text
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/{model_id}"
        f":embedContent?key={api_key}"
    )
    embeddings: List[List[float]] = []
    with httpx.Client(timeout=60.0) as client:
        for text in texts:
            payload = {"model": model_id, "content": {"parts": [{"text": text}]}}
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            embeddings.append(data["embedding"]["values"])
    return embeddings


def _embed_gemini_batch(texts: List[str], model_id: str, api_key: str) -> List[List[float]]:
    """Batch embed using Gemini batchEmbedContents endpoint."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/{model_id}"
        f":batchEmbedContents?key={api_key}"
    )
    requests_payload = [
        {"model": model_id, "content": {"parts": [{"text": t}]}}
        for t in texts
    ]
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json={"requests": requests_payload})
        response.raise_for_status()
        data = response.json()
    return [item["values"] for item in data["embeddings"]]
