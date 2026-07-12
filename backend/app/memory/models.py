"""Semantic memory observability ORM (Step 11) — one telemetry row per graph-retrieval query.

Records how a semantic-memory retrieval ran (entities recognized, traversal depth/size, per-stage
timings, cache hit, hit counts, confidence). Never duplicates GraphConstructionLog (build telemetry) or
RetrievalLog (vector search) — this owns the graph-RETRIEVAL layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SemanticMemoryLog(Base):
    __tablename__ = "semantic_memory_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # smem_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="graph")   # graph | hybrid
    recognized_entities: Mapped[list | None] = mapped_column(JSON, default=None)

    seed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    traversal_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    traversal_strategy: Mapped[str] = mapped_column(String(8), nullable=False, default="bfs")
    neighborhood_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_traversed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    graph_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    avg_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # per-stage timings (ms)
    recognition_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    traversal_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fusion_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    context_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_smem_ws_created", "workspace_id", "created_at"),
    )
