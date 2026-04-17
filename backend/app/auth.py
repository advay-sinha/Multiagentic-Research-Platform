"""MongoDB-backed auth: signup, login, JWT bearer, current-user dependency.

Users are stored in ``users`` collection with ``email`` (unique) and a
bcrypt-hashed ``password_hash``. JWT is HS256 signed with ``JWT_SECRET``.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from .mongo import get_db, last_error as _mongo_last_error
from .schemas import (
    LoginRequest,
    QueryHistoryItem,
    QueryHistoryResponse,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger("research_api")

_JWT_SECRET = os.environ.get("JWT_SECRET") or "dev-insecure-jwt-secret-change-me"
_JWT_ALG = "HS256"
_JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS") or "168")  # 7 days

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(plain: str) -> str:
    import bcrypt
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _issue_token(user_id: str, email: str) -> str:
    import jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALG)


def _decode_token(token: str) -> Dict[str, Any]:
    import jwt
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _require_db():
    db = get_db()
    if db is None:
        reason = _mongo_last_error() or "MONGO_URI not configured"
        raise HTTPException(
            status_code=503,
            detail=f"Auth unavailable — {reason}",
        )
    return db


def current_user_optional(
    authorization: Optional[str] = Header(default=None),
) -> Optional[Dict[str, Any]]:
    """Resolve user from Bearer token. Returns ``None`` if no/invalid header.

    Used by /v1/query so unauthenticated requests still work (no history saved).
    """
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        payload = _decode_token(parts[1])
    except HTTPException:
        return None
    return {"user_id": payload.get("sub"), "email": payload.get("email")}


def current_user_required(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    payload = _decode_token(parts[1])
    return {"user_id": payload.get("sub"), "email": payload.get("email")}


@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest) -> TokenResponse:
    db = _require_db()
    email = payload.email.strip().lower()
    if db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email already registered")
    user_id = f"u_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": payload.name or email.split("@")[0],
        "password_hash": _hash_password(payload.password),
        "created_at": now_iso,
    })
    token = _issue_token(user_id, email)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(user_id=user_id, email=email, name=payload.name or email.split("@")[0]),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    db = _require_db()
    email = payload.email.strip().lower()
    user = db.users.find_one({"email": email})
    if not user or not _verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = _issue_token(user["user_id"], email)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            user_id=user["user_id"],
            email=email,
            name=user.get("name", email.split("@")[0]),
        ),
    )


@router.get("/me", response_model=UserResponse)
def me(user=Depends(current_user_required)) -> UserResponse:
    db = _require_db()
    record = db.users.find_one({"user_id": user["user_id"]})
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        user_id=record["user_id"],
        email=record["email"],
        name=record.get("name", record["email"].split("@")[0]),
    )


@router.get("/history", response_model=QueryHistoryResponse)
def history(
    limit: int = 20,
    user=Depends(current_user_required),
) -> QueryHistoryResponse:
    db = _require_db()
    cursor = (
        db.query_history
        .find({"user_id": user["user_id"]})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 100)))
    )
    items = []
    for doc in cursor:
        items.append(QueryHistoryItem(
            query=doc.get("query", ""),
            answer_id=doc.get("answer_id", ""),
            trace_id=doc.get("trace_id", ""),
            confidence_score=float(doc.get("confidence_score", 0.0)),
            created_at=doc.get("created_at", ""),
            citation_count=int(doc.get("citation_count", 0)),
        ))
    return QueryHistoryResponse(items=items)
