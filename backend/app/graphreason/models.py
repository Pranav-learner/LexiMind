"""Graph reasoning observability ORM (Step 12) — one telemetry row per reasoning query.

Records how a reasoning ran (traversal depth, relationships traversed, inference/path counts, per-stage
timings, cache hit, complexity, confidence, verification). Inferred relationships are NOT a new table —
they are persisted as `GraphRelationship` rows with `status="inferred"` (kept out of retrieval, which is
`active_only`). Never duplicates GraphConstructionLog / SemanticMemoryLog / VerificationLog.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GraphReasoningLog(Base):
    __tablename__ = "graph_reasoning_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # gr_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default="graphreason-v1")

    seed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    traversal_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationships_traversed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paths_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inference_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dependency_chains: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    root_causes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_complexity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_band: Mapped[str] = mapped_column(String(12), nullable=False, default="low")
    verification_status: Mapped[str] = mapped_column(String(12), nullable=False, default="not_run")

    # per-stage timings (ms)
    recognition_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    paths_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inference_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verification_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    report: Mapped[dict | None] = mapped_column(JSON, default=None)   # explanation + complexity snapshot
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_grlog_ws_created", "workspace_id", "created_at"),
    )
