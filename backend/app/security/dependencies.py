"""FastAPI dependencies for Enterprise Security & Governance.

Provides rate-limiting guards and resolves request identities (JWT, API keys,
and Service Accounts) with tenant/workspace scoping.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.models import User
from app.auth.repository import UserRepository
from app.db.base import get_db
from app.security import services
from app.security.errors import RateLimitExceededError, UnauthorizedError
from app.security.models import ApiKey, ServiceAccount

# In-memory sliding window rate limiter cache
# Key: actor_id, Value: list of timestamp floats
_rate_limit_cache: dict[str, list[float]] = {}


def check_rate_limit(actor_id: str, limit: int = 100, window_secs: int = 60) -> None:
    """Sliding-window log rate limiter. Raises RateLimitExceededError on violation."""
    now = time.time()
    if actor_id not in _rate_limit_cache:
        _rate_limit_cache[actor_id] = []

    # Keep only timestamps inside active window
    timestamps = [t for t in _rate_limit_cache[actor_id] if now - t < window_secs]
    if len(timestamps) >= limit:
        raise RateLimitExceededError(f"Rate limit exceeded: {limit} requests per {window_secs} seconds.")

    timestamps.append(now)
    _rate_limit_cache[actor_id] = timestamps


def resolve_actor_identity(
    db: Session,
    authorization: str | None = None,
    x_api_key: str | None = None,
) -> dict[str, Any] | None:
    """Helper to authenticate credentials and return active identity dictionary."""
    # 1. Check API Key Header (X-API-Key)
    if x_api_key:
        api_key = services.verify_api_key(db, x_api_key)
        if api_key:
            return _build_actor_context(db, api_key)

    # 2. Check Authorization Header (Bearer <token> or ApiKey <key>)
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2:
            scheme, credential = parts[0].lower(), parts[1].strip()
            if scheme == "bearer":
                # Standard JWT auth
                user_id = security.decode_token(credential)
                if user_id:
                    user = UserRepository(db).get_by_id(user_id)
                    if user:
                        return {
                            "id": user.id,
                            "type": "user",
                            "email": user.email,
                            "name": user.display_name,
                        }
            elif scheme == "apikey":
                api_key = services.verify_api_key(db, credential)
                if api_key:
                    return _build_actor_context(db, api_key)

    return None


def _build_actor_context(db: Session, api_key: ApiKey) -> dict[str, Any]:
    """Helper to structure context metadata from a validated API Key."""
    if api_key.user_id:
        user = UserRepository(db).get_by_id(api_key.user_id)
        if user:
            return {
                "id": user.id,
                "type": "user",
                "email": user.email,
                "name": user.display_name,
                "scopes": api_key.scopes,
            }
    elif api_key.service_account_id:
        sa = db.query(ServiceAccount).filter(ServiceAccount.id == api_key.service_account_id).first()
        if sa:
            return {
                "id": sa.id,
                "type": "service_account",
                "email": None,
                "name": sa.name,
                "scopes": api_key.scopes,
                "organization_id": sa.organization_id,
            }

    raise UnauthorizedError("API Key identity is invalid.")


def get_active_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """FastAPI Dependency: extracts identity, rate limits, and yields actor payload."""
    actor = resolve_actor_identity(db, authorization, x_api_key)
    if not actor:
        raise HTTPException(status_code=401, detail="Authentication credentials invalid or missing.")

    # Apply rate limiting
    try:
        check_rate_limit(actor["id"])
    except RateLimitExceededError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    # Save to request state for middleware retrieval
    request.state.actor = actor
    return actor
