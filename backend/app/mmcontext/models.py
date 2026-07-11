"""Multimodal context ORM — Phase 4, Module 4: Multimodal Context Engineering Engine.

ONE new table: `ContextBuildLog` — an append-only record of each multimodal context build (query,
intent, dedup reduction, compression ratio, token usage, per-stage latency). It powers the
observability endpoint + future context-quality dashboards (Phase 9) with a single cheap insert per
build — the assembly hot path stays stateless. Nothing here changes Phase-2 (`app/context/`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContextBuildLog(Base):
    __tablename__ = "context_build_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"cbl_{uuid.uuid4().hex[:16]}")
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_intent: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    modalities: Mapped[list | None] = mapped_column(JSON, default=None)

    retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    after_dedup: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_reduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0..1
    compression_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage_ms: Mapped[dict | None] = mapped_column(JSON, default=None)  # {dedup, rank, budget, compress, assemble, prompt}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_cbl_ws_created", "workspace_id", "created_at"),)
