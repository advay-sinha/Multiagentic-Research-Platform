"""RAG retrieval + answer cache, keyed by (user_id, query).

Stored in Mongo ``query_cache`` collection with a TTL index on ``expires_at``.
Falls back to an in-process dict when Mongo is unavailable so dev/offline still
benefits from same-session cache hits.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .mongo import get_db

logger = logging.getLogger("research_api")

_MEMORY: Dict[str, Dict[str, Any]] = {}
_MEMORY_MAX = 512

_TTL_SECONDS = int(os.environ.get("RAG_CACHE_TTL_SECONDS") or str(60 * 60 * 24 * 7))  # 7 days


def query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()


def _key(user_id: str, qhash: str) -> str:
    return f"{user_id}::{qhash}"


def get(user_id: str, query: str) -> Optional[Dict[str, Any]]:
    qhash = query_hash(query)
    db = get_db()
    if db is not None:
        doc = db.query_cache.find_one({"user_id": user_id, "query_hash": qhash})
        if doc:
            doc.pop("_id", None)
            return doc
    # Memory fallback
    hit = _MEMORY.get(_key(user_id, qhash))
    if hit and hit.get("expires_at_ts", 0) > time.time():
        return hit
    return None


def put(user_id: str, query: str, payload: Dict[str, Any]) -> None:
    qhash = query_hash(query)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS)
    doc = {
        "user_id": user_id,
        "query_hash": qhash,
        "query": query,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
    }
    db = get_db()
    if db is not None:
        db.query_cache.update_one(
            {"user_id": user_id, "query_hash": qhash},
            {"$set": doc},
            upsert=True,
        )
        return
    # Memory fallback — bounded FIFO.
    if len(_MEMORY) >= _MEMORY_MAX:
        for k in list(_MEMORY.keys())[: _MEMORY_MAX // 10]:
            _MEMORY.pop(k, None)
    mem_doc = dict(doc)
    mem_doc["expires_at_ts"] = time.time() + _TTL_SECONDS
    mem_doc["expires_at"] = expires_at.isoformat()
    _MEMORY[_key(user_id, qhash)] = mem_doc
