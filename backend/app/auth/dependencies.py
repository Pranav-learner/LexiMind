"""FastAPI dependencies for authentication.

`get_current_user` is the single guard every protected route depends on. It extracts the
bearer token, verifies it, loads the user, and raises 401 otherwise. Workspace routes
depend on `get_current_user_id` so they never see the web framework's auth mechanics.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.models import User
from app.auth.repository import UserRepository
from app.db.base import get_db


def _unauthorized(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    user_id = security.decode_token(token)
    if not user_id:
        raise _unauthorized("Invalid or expired token.")
    user = UserRepository(db).get_by_id(user_id)
    if not user:
        raise _unauthorized("User no longer exists.")
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    """Convenience for routes that only need the owner id (e.g. workspace scoping)."""
    return user.id


def get_optional_user_id(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str | None:
    """Like get_current_user_id but returns None instead of 401 when unauthenticated.

    Used by the legacy upload/query routes so they keep working without a token (backward
    compatibility) while still scoping to the owner when a valid token IS supplied.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    user_id = security.decode_token(authorization.split(" ", 1)[1].strip())
    if not user_id:
        return None
    user = UserRepository(db).get_by_id(user_id)
    return user.id if user else None
