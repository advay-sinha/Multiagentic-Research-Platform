"""MongoDB client + collection helpers.

Connection is optional — if ``MONGO_URI`` is not set, ``get_db()`` returns
``None`` and all consumers fall back to degraded behaviour (no auth, no
user history, no cache). Tests and offline dev remain runnable.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("research_api")

_client = None
_db = None
_init_attempted = False
_last_error: Optional[str] = None


def get_db():
    """Return a ``pymongo.Database`` or ``None`` if Mongo isn't configured."""
    global _client, _db, _init_attempted, _last_error
    if _init_attempted:
        return _db
    _init_attempted = True
    uri = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or ""
    if not uri:
        _last_error = "MONGO_URI / MONGODB_URI not set"
        logger.info("%s — auth + history disabled", _last_error)
        return None
    try:
        from pymongo import MongoClient, ASCENDING
    except ImportError as exc:
        _last_error = f"pymongo not installed ({exc})"
        logger.warning("%s — run `pip install pymongo`", _last_error)
        return None
    try:
        db_name = os.environ.get("MONGO_DB") or "mars"
        _client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        _client.server_info()  # force connection check
        _db = _client[db_name]
        _ensure_indexes(_db, ASCENDING)
        logger.info("MongoDB connected: %s/%s", uri.split("@")[-1], db_name)
        return _db
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("MongoDB unavailable (%s) — auth + history disabled", _last_error)
        _db = None
        return None


def last_error() -> Optional[str]:
    """Reason Mongo is unavailable, for surfacing in 503 responses."""
    return _last_error


def _ensure_indexes(db, ASCENDING) -> None:
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.query_history.create_index([("user_id", ASCENDING), ("created_at", -1)])
    db.query_history.create_index([("user_id", ASCENDING), ("query_hash", ASCENDING)])
    # TTL index: cache docs auto-expire using ``expires_at`` field.
    db.query_cache.create_index("expires_at", expireAfterSeconds=0)
    db.query_cache.create_index([("user_id", ASCENDING), ("query_hash", ASCENDING)], unique=True)


def is_available() -> bool:
    return get_db() is not None
