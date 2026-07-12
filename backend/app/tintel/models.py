"""Temporal Intelligence ORM — the CANONICAL persistence for chapters, topics, and timeline events.

Phase 5 Module 3 introduces this as *foundational persistence only*: production-ready entities,
indexes, and storage that Module 3 (Temporal Retrieval & Context) retrieves over. Their initial
values are produced by LIGHTWEIGHT derivation (see `derivation.py`) from Module-1 transcript /
speaker / scene data — a temporary population strategy.

The FULL Temporal Intelligence Engine (Phase 5 Module 2 — advanced semantic topic segmentation,
AI-generated chapter titles, event classification, conversation understanding) will later ENRICH
these same rows in place (`source` flips from "derived" to "model", titles/summaries improve). This
schema is canonical and must remain stable across the project — Module 2 upgrades, never replaces it.

- `Chapter`        — a coarse section of a recording ([start_ms,end_ms) + title/summary/keywords).
- `Topic`          — a topic segment ([start_ms,end_ms) + label/keywords/salience).
- `TimelineEvent`  — a point/interval event on the timeline (speaker_change / scene_change /
                     topic_shift / chapter_start / keypoint …), anchored at `timestamp_ms`.

Every row is workspace + owner + document scoped and carries `source`/`confidence`/`pipeline_version`
so a later, smarter pass is distinguishable from the derived baseline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Bumped by Module 2 when it re-derives with real intelligence.
TEMPORAL_PIPELINE_VERSION = "tintel-v1-derived"

CHAPTER_SOURCES = ("derived", "model")
EVENT_TYPES = (
    "chapter_start", "scene_change", "speaker_change", "topic_shift", "silence", "keypoint",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Chapter(Base):
    __tablename__ = "media_chapters"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("chap"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(40), default=None)  # provenance → MediaJob

    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text, default=None)       # Module 2 fills this in
    keywords: Mapped[list | None] = mapped_column(JSON, default=None)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[str] = mapped_column(String(12), nullable=False, default="derived")  # derived|model
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    pipeline_version: Mapped[str] = mapped_column(String(30), nullable=False, default=TEMPORAL_PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_chapters_doc_start", "document_id", "start_ms"),
        Index("ix_chapters_ws_doc", "workspace_id", "document_id"),
    )


class Topic(Base):
    __tablename__ = "media_topics"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("top"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(40), default=None)

    topic_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    keywords: Mapped[list | None] = mapped_column(JSON, default=None)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    salience: Mapped[float | None] = mapped_column(Float, default=None)   # how dominant the topic is

    source: Mapped[str] = mapped_column(String(12), nullable=False, default="derived")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    pipeline_version: Mapped[str] = mapped_column(String(30), nullable=False, default=TEMPORAL_PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_topics_doc_start", "document_id", "start_ms"),
        Index("ix_topics_ws_doc", "workspace_id", "document_id"),
    )


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("evt"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(40), default=None)

    event_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, default="keypoint")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, default=None)   # Module 2 fills this in

    timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # primary anchor
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    speaker_id: Mapped[str | None] = mapped_column(String(40), default=None)
    scene_id: Mapped[str | None] = mapped_column(String(40), default=None)
    chapter_id: Mapped[str | None] = mapped_column(String(40), default=None)

    source: Mapped[str] = mapped_column(String(12), nullable=False, default="derived")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    pipeline_version: Mapped[str] = mapped_column(String(30), nullable=False, default=TEMPORAL_PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_events_doc_ts", "document_id", "timestamp_ms"),
        Index("ix_events_doc_type", "document_id", "event_type"),
        Index("ix_events_ws_doc", "workspace_id", "document_id"),
    )
