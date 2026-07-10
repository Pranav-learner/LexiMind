"""User ORM model.

Minimal by design (Phase 3, Module 1): just enough identity to make `owner_id` on a
Workspace real and to scope data per user. No roles/teams/permissions yet — those arrive
with collaboration in a later module, and the schema is shaped so they can be added without
rewriting existing rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("user"))
    # Email is the login handle; unique + indexed for fast lookups on login.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
