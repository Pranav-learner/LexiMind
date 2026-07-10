"""Workspace ORM model — the core entity of Phase 3.

A Workspace is an isolated knowledge environment. Every future artifact (documents, chats,
notes, flashcards, summaries) belongs to exactly one workspace, which is why the row carries
denormalized per-type counters: they let the dashboard render counts for thousands of
workspaces without an N+1 fan-out of COUNT(*) queries.

Scalability / indexing rationale:
- `owner_id` is indexed — every list query filters by owner.
- `is_archived` is indexed — the dashboard splits active vs archived.
- (`owner_id`, `name`) has a composite index for fast duplicate-name checks and lookups.
- Soft delete via `deleted_at` (nullable): deletion is reversible unless a caller asks for a
  hard delete. Uniqueness of names is enforced in the service among *non-deleted* rows so a
  name frees up after permanent deletion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return f"ws_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# The set of denormalized counters. Centralized so retrieval/other modules can increment a
# counter by name without hard-coding column lists in three places.
COUNTER_FIELDS = (
    "document_count",
    "chat_count",
    "note_count",
    "flashcard_count",
    "summary_count",
)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="📁")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366f1")

    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    # Soft-delete tombstone. NULL => live row. Set => hidden from all normal queries.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Denormalized counters (kept in sync by the owning modules on ingest/create/delete).
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chat_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flashcard_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        # Composite index: duplicate-name checks and per-owner name lookups.
        Index("ix_workspaces_owner_name", "owner_id", "name"),
    )
