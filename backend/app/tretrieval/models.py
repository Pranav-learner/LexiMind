"""Temporal retrieval ORM — one observability table (mirrors mmretrieval.RetrievalLog).

`TemporalSearchLog` records each temporal search's shape + latencies (query analysis, per-retriever,
fusion, rerank, context-assembly, prompt-build) so Step-14 observability + future dashboards have a
cheap source. No retrieval *data* is stored here — retrieval reads the canonical media + tintel tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TemporalSearchLog(Base):
    __tablename__ = "temporal_search_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"tsl_{uuid.uuid4().hex[:16]}")
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(40), default=None)

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intents: Mapped[list | None] = mapped_column(JSON, default=None)         # activated retrievers
    primary: Mapped[str] = mapped_column(String(20), nullable=False, default="transcript")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    analysis_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fusion_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rerank_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    context_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retriever_stats: Mapped[dict | None] = mapped_column(JSON, default=None)  # modality -> {ms,count}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_tsl_ws_created", "workspace_id", "created_at"),
    )
