from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from typing import Dict, List, Tuple

import httpx

from .settings import load_settings

_logger = logging.getLogger("research_api")

# Module-level cache so retries / repeated ingest of same text don't re-embed.
# Key: (model_id, dim, sha256(text)). Bounded by _EMBED_CACHE_MAX.
_EMBED_CACHE: Dict[Tuple[str, int, str], List[float]] = {}
_EMBED_CACHE_MAX = 4096

# Remember which configured model id has been superseded by a fallback so we
# don't hit the 404 again for every batch.
_MODEL_RESOLUTION: Dict[str, str] = {}
_FALLBACK_MODELS = ["models/gemini-embedding-001"]

# Provider health state — when Gemini quota is exhausted we mark it unhealthy
# until ``_gemini_cooldown_until`` passes, then retry.
_gemini_cooldown_until: float = 0.0
_GEMINI_COOLDOWN_AFTER_EXHAUST = 300.0  # seconds

# Lazy local fallback — load fastembed only when needed (heavy import).
_local_embedder = None
_LOCAL_MODEL_NAME = os.environ.get("LOCAL_EMBED_MODEL") or "BAAI/bge-base-en-v1.5"  # 768-dim


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed texts using the first healthy provider.

    Tries providers in order per ``EMBED_PROVIDER_ORDER`` env (default
    ``gemini,local``). On Gemini 429/exhaustion falls back to local
    fastembed so ingest / retrieval never hard-fails on quota.
    """
    settings = load_settings()
    # Default: Gemini only. On 429/exhaustion Gemini raises and callers
    # (pgvector_store.search/add_document, retriever cache warm) fall back to
    # the in-memory DOCUMENT_STORE (TF-IDF keyword search). Opt into fastembed
    # local fallback by setting EMBED_PROVIDER_ORDER=gemini,local.
    order = [p.strip().lower() for p in (os.environ.get("EMBED_PROVIDER_ORDER") or "gemini").split(",") if p.strip()]
    last_exc: Exception | None = None
    for provider in order:
        if provider == "gemini":
            if not settings.gemini_api_key:
                continue
            if time.monotonic() < _gemini_cooldown_until:
                _logger.info("Gemini embed in cooldown, skipping to next provider")
                continue
            try:
                return _embed_gemini(
                    texts,
                    settings.embedding_model,
                    settings.gemini_api_key,
                    settings.embedding_dim,
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in (429, 402, 403):
                    _set_gemini_cooldown()
                    _logger.warning(
                        "Gemini embed exhausted (%d) — cooling down %ds, trying next provider",
                        exc.response.status_code, int(_GEMINI_COOLDOWN_AFTER_EXHAUST),
                    )
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                _logger.warning("Gemini embed failed: %s — trying next provider", exc)
                continue
        elif provider == "local":
            try:
                return _embed_local(texts, settings.embedding_dim)
            except Exception as exc:
                last_exc = exc
                _logger.warning("Local embed failed: %s", exc)
                continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(
        "No embedding provider available. Set GEMINI_API_KEY or install fastembed."
    )


def _set_gemini_cooldown() -> None:
    global _gemini_cooldown_until
    _gemini_cooldown_until = time.monotonic() + _GEMINI_COOLDOWN_AFTER_EXHAUST


def _get_local_embedder():
    """Lazy-load fastembed. Heavy import (~30s first call downloads model)."""
    global _local_embedder
    if _local_embedder is None:
        from fastembed import TextEmbedding  # type: ignore[import-untyped]
        _logger.info("Loading local fastembed model: %s", _LOCAL_MODEL_NAME)
        _local_embedder = TextEmbedding(model_name=_LOCAL_MODEL_NAME)
    return _local_embedder


def _embed_local(texts: List[str], dim: int) -> List[List[float]]:
    """Embed with fastembed. bge-base-en-v1.5 is 768-dim — matches Gemini default."""
    embedder = _get_local_embedder()
    # Resolve cache first so repeated chunks skip the model.
    model_key = f"local:{_LOCAL_MODEL_NAME}"
    results: List[List[float] | None] = [None] * len(texts)
    misses: List[Tuple[int, str]] = []
    for i, text in enumerate(texts):
        hit = _EMBED_CACHE.get(_cache_key(model_key, dim, text))
        if hit is not None:
            results[i] = hit
        else:
            misses.append((i, text))
    if misses:
        miss_texts = [t for _, t in misses]
        vectors = [list(v) for v in embedder.embed(miss_texts)]
        for (i, text), vec in zip(misses, vectors):
            # Match configured dim by truncation or zero-padding.
            if len(vec) > dim:
                vec = vec[:dim]
            elif len(vec) < dim:
                vec = vec + [0.0] * (dim - len(vec))
            _cache_store(_cache_key(model_key, dim, text), vec)
            results[i] = vec
    return [r for r in results if r is not None]


def _cache_key(model_id: str, dim: int, text: str) -> Tuple[str, int, str]:
    return (model_id, dim, hashlib.sha256(text.encode("utf-8")).hexdigest())


def _cache_store(key: Tuple[str, int, str], vec: List[float]) -> None:
    if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX:
        # Drop oldest ~10% to keep bound. dict preserves insertion order.
        drop = max(1, _EMBED_CACHE_MAX // 10)
        for k in list(_EMBED_CACHE.keys())[:drop]:
            _EMBED_CACHE.pop(k, None)
    _EMBED_CACHE[key] = vec


def _embed_gemini(texts: List[str], model: str, api_key: str, dim: int) -> List[List[float]]:
    """Embed texts via Gemini batchEmbedContents.

    ``dim`` pins the returned vector size via ``outputDimensionality`` to
    match the pgvector ``VECTOR(dim)`` schema. Uses an in-process cache so
    re-ingesting the same chunks skips the network round-trip entirely.
    On 429 we honour Gemini's ``retryDelay`` hint when present.
    Falls back to ``gemini-embedding-001`` if the configured model 404s.
    """
    configured = model if model.startswith("models/") else f"models/{model}"
    model_id = _MODEL_RESOLUTION.get(configured, configured)

    # Resolve cached vectors first; only fetch the misses.
    results: List[List[float] | None] = [None] * len(texts)
    misses: List[Tuple[int, str]] = []
    for i, text in enumerate(texts):
        hit = _EMBED_CACHE.get(_cache_key(model_id, dim, text))
        if hit is not None:
            results[i] = hit
        else:
            misses.append((i, text))

    if misses:
        try:
            fetched = _embed_gemini_batch([t for _, t in misses], model_id, api_key, dim)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and model_id != _FALLBACK_MODELS[-1]:
                # Configured model unavailable — resolve to first working fallback
                # and retry. Memoize so subsequent batches skip the 404.
                for fb in _FALLBACK_MODELS:
                    if fb == model_id:
                        continue
                    _logger.warning(
                        "Gemini embed model %s returned 404; falling back to %s",
                        model_id, fb,
                    )
                    _MODEL_RESOLUTION[configured] = fb
                    model_id = fb
                    try:
                        fetched = _embed_gemini_batch(
                            [t for _, t in misses], model_id, api_key, dim
                        )
                        break
                    except httpx.HTTPStatusError as exc2:
                        if exc2.response.status_code == 404:
                            continue
                        raise
                else:
                    raise
            else:
                raise
        for (i, text), vec in zip(misses, fetched):
            _cache_store(_cache_key(model_id, dim, text), vec)
            results[i] = vec

    return [r for r in results if r is not None]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# Tunables — override via env if you have paid quota.
_GEMINI_BATCH_LIMIT = _env_int("GEMINI_EMBED_BATCH", 50)        # ≤100 server cap; smaller = less TPM spike.
_GEMINI_INTER_BATCH_DELAY = _env_float("GEMINI_EMBED_DELAY", 3.0)
# 2 total attempts on 429 (1 initial + 1 retry) — fail fast on quota, callers
# fall through to in-memory DOCUMENT_STORE rather than waiting out long backoffs.
_GEMINI_429_RETRIES = _env_int("GEMINI_EMBED_RETRIES", 1)
_GEMINI_429_BASE = _env_float("GEMINI_EMBED_BACKOFF_BASE", 5.0)  # exp backoff base seconds
_GEMINI_429_CAP = _env_float("GEMINI_EMBED_BACKOFF_CAP", 60.0)   # max single wait


def _embed_gemini_batch(texts: List[str], model_id: str, api_key: str, dim: int) -> List[List[float]]:
    if not texts:
        return []
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/{model_id}"
        f":batchEmbedContents?key={api_key}"
    )
    all_vectors: List[List[float]] = []
    with httpx.Client(timeout=120.0) as client:
        batches = [texts[i : i + _GEMINI_BATCH_LIMIT] for i in range(0, len(texts), _GEMINI_BATCH_LIMIT)]
        for idx, sub in enumerate(batches):
            if idx > 0:
                _interruptible_sleep(_GEMINI_INTER_BATCH_DELAY)
            payload = {
                "requests": [
                    {
                        "model": model_id,
                        "content": {"parts": [{"text": t}]},
                        "outputDimensionality": dim,
                    }
                    for t in sub
                ]
            }
            data = _post_embed_with_retry(client, url, payload)
            all_vectors.extend(item["values"] for item in data["embeddings"])
    return all_vectors


def _parse_retry_delay(body: dict) -> float | None:
    """Extract retryDelay (e.g. '21s') from Gemini 429 error details."""
    try:
        details = body.get("error", {}).get("details", []) or []
        for d in details:
            if "RetryInfo" in str(d.get("@type", "")):
                raw = d.get("retryDelay")
                if isinstance(raw, str) and raw.endswith("s"):
                    return float(raw[:-1])
                if isinstance(raw, (int, float)):
                    return float(raw)
    except Exception:
        pass
    return None


def _backoff_wait(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        hint = _parse_retry_delay(response.json())
        if hint is not None:
            return min(hint + random.uniform(0.5, 2.0), _GEMINI_429_CAP)
    except Exception:
        pass
    # Exponential backoff with jitter, capped.
    wait = min(_GEMINI_429_BASE * (2 ** attempt), _GEMINI_429_CAP)
    return wait + random.uniform(0.0, wait * 0.25)


def _interruptible_sleep(seconds: float) -> None:
    """Chunked sleep so Ctrl+C / SIGINT can break out within ~0.25s instead of
    blocking for the full 429 backoff (up to 60s)."""
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


def _post_embed_with_retry(client: httpx.Client, url: str, payload: dict) -> dict:
    last: httpx.Response | None = None
    for attempt in range(_GEMINI_429_RETRIES + 1):
        response = client.post(url, json=payload)
        last = response
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        if attempt == _GEMINI_429_RETRIES:
            break
        wait = _backoff_wait(response, attempt)
        _logger.warning(
            "Gemini embed 429 — sleeping %.1fs (attempt %d/%d)",
            wait, attempt + 1, _GEMINI_429_RETRIES + 1,
        )
        _interruptible_sleep(wait)
    assert last is not None
    last.raise_for_status()
    return last.json()
