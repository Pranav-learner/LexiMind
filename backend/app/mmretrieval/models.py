"""Multimodal retrieval ORM — Phase 4, Module 3: Multimodal Retrieval Engine.

ONE new table: `RetrievalLog` — an append-only record of each multimodal search (query, activated
modalities, per-retriever latency + counts, fusion/rerank latency, result count). It powers the
retrieval-statistics endpoint and future retrieval-quality dashboards (Phase 9) WITHOUT touching the
hot path (a single cheap insert per search). Retrieval itself is stateless; nothing here changes
Phase-1 retrieval or the FAISS index.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"rlog_{uuid.uuid4().hex[:16]}")
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intents: Mapped[list | None] = mapped_column(JSON, default=None)        # activated modalities
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retriever_stats: Mapped[dict | None] = mapped_column(JSON, default=None)  # {modality: {ms, count}}
    fusion_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rerank_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_rlogs_ws_created", "workspace_id", "created_at"),)
