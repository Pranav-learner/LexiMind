"""Verification observability ORM (Step 12) — one telemetry table for the trust layer.

`VerificationLog` records how a verification ran (mode, per-stage timings, claim/evidence/contradiction/
citation counts, confidence distribution) AND stores the structured `report` so the Verification
Inspector + APIs can render it without re-running verification. It links to the run it verified via
`execution_id` (an AgentTaskLog / AgentExecutionLog id) but NEVER duplicates AgentExecutionLog — that
table owns run tracing; this one owns verification telemetry.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VerificationLog(Base):
    __tablename__ = "verification_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # ver_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # task/exec verified
    agent: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="fast")   # off | fast | thorough

    # outcome
    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False, default="warning")
    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_band: Mapped[str] = mapped_column(String(12), nullable=False, default="low")

    # counts
    claims_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicting: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradictions_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # timings (ms)
    verification_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    review_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    report: Mapped[dict | None] = mapped_column(JSON, default=None)   # VerificationReport.to_dict()
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_verlog_ws_created", "workspace_id", "created_at"),
        Index("ix_verlog_exec", "execution_id"),
    )
