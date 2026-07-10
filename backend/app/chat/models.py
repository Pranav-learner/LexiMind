"""Chat ORM models — Phase 3, Module 4: Persistent AI Chat Workspace.

Three NEW tables (created cleanly by `create_all`, no migration needed):

- `Conversation` — a long-lived, workspace-scoped chat thread.
- `Message`      — one turn (user / assistant / system) in a conversation.
- `MessageCitation` — the grounded provenance attached to an assistant message (reuses the
  same Workspace → Document → Page → Chunk → Text mapping Modules 2–3 established).

Two-store philosophy is unchanged: structured rows live in SQLite; vectors stay in FAISS. A
conversation carries `workspace_id` so retrieval is ALWAYS scoped to the active workspace, and
a citation carries the vector `document_id` so the UI can resolve it to a Document and jump into
the Module-3 viewer.

Future-proofing (columns present, features NOT implemented here):
- multi-model: `model_name`, `temperature`, `system_prompt_version` on the conversation.
- conversation branching: `branched_from_message_id` (nullable).
- document-scoped chats: `document_scope` (nullable JSON list of document ids).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conv_id() -> str:
    return f"conv_{uuid.uuid4().hex[:16]}"


def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:16]}"


def _cit_id() -> str:
    return f"cit_{uuid.uuid4().hex[:16]}"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_conv_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New chat")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_pinned: Mapped[bool] = mapped_column(default=False, index=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(default=False, index=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Retrieval scope: null = whole workspace; else a JSON list of document ids to restrict to.
    document_scope: Mapped[list | None] = mapped_column(JSON, default=None)

    # Multi-model future-proofing.
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    system_prompt_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")

    # Branching future-proofing (nullable; unused for now).
    branched_from_message_id: Mapped[str | None] = mapped_column(String(40), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        # Every list query scopes by (owner, workspace); pinned/archived split the views.
        Index("ix_conversations_owner_ws", "owner_id", "workspace_id"),
        # Recency ordering (default sort) within a workspace.
        Index("ix_conversations_ws_last", "workspace_id", "last_message_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_msg_id)
    conversation_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Telemetry (per Module-4 spec).
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieval_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Free-form: status ("ok"/"error"/"cancelled"), model, future image/audio parts, etc.
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        # History reads are always (conversation ordered by time).
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_cit_id)
    message_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # Vector document id (resolvable to a Document via the Module-3 /by-vector endpoint).
    document_id: Mapped[str | None] = mapped_column(String(40), default=None)
    chunk_id: Mapped[str | None] = mapped_column(String(80), default=None)
    page_number: Mapped[int | None] = mapped_column(Integer, default=None)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    citation_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
