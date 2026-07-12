"""Media AI Workspace ORM — one observability table (Phase 5, Module 4).

The orchestrator itself owns NO business logic and reuses every existing domain. Its only persistence
is this single interaction-telemetry sink (Step 15) — consistent with every prior module owning one
log table (RetrievalLog / TemporalSearchLog / ProcessingLog / ContextBuildLog). It records the
front-of-house interactions that have no existing home (playback, timeline/transcript/citation clicks,
chapter/speaker navigation) so the analytics platform can surface how users engage with media.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The interaction events tracked (Step 15). Free-form string column so new surfaces need no migration.
INTERACTION_TYPES = (
    "playback", "seek", "timeline_click", "transcript_click", "citation_click",
    "chapter_nav", "speaker_nav", "media_chat", "ai_action", "media_search",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MediaInteractionEvent(Base):
    __tablename__ = "media_interaction_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"mie_{uuid.uuid4().hex[:16]}")
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(40), default=None)

    event_type: Mapped[str] = mapped_column(String(30), nullable=False, default="playback")
    target: Mapped[str | None] = mapped_column(String(200), default=None)     # e.g. citation id / chapter id
    position_ms: Mapped[int | None] = mapped_column(Integer, default=None)     # playback/seek position
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_mie_ws_created", "workspace_id", "created_at"),
        Index("ix_mie_ws_type", "workspace_id", "event_type"),
    )
