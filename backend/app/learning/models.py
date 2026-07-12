"""ORM models for Continuous Learning & Feedback (Phase 8, Module 4).

Three NEW tables (no existing `*Log` expresses these):
  Feedback              — unified real-world feedback (thumbs/star/text/correction/citation/…), auth or anon.
  LearningRecommendation — an explainable, GOVERNED proposal (reason/evidence/impact/confidence) that flows
                          through the human review queue (status pending → approved | rejected). This IS the
                          review queue + the audit trail; recommendations are never auto-applied.
  LearningCycleLog      — one learning-cycle summary (feedback/failures/clusters/recs/approvals).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Feedback(Base):
    __tablename__ = "learn_feedback"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # nullable = anonymous
    target_type: Mapped[str] = mapped_column(String(30), default="answer")   # answer|citation|retrieval|agent|graph|media|workspace
    target_id: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(30), default="thumbs")          # thumbs_up|thumbs_down|star|text|correction|citation
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)        # 1..5 for stars
    sentiment: Mapped[str] = mapped_column(String(12), default="neutral")     # positive|negative|neutral
    comment: Mapped[str] = mapped_column(Text, default="")
    correction: Mapped[str] = mapped_column(Text, default="")
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningRecommendation(Base):
    __tablename__ = "learn_recommendations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(24), default="prompt")       # prompt|retrieval|agent|dataset|routing|graph|context
    title: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    affected_components: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(12), default="info")         # info|warning|critical
    cluster_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending|approved|rejected
    reviewer: Mapped[str | None] = mapped_column(String(40), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningCycleLog(Base):
    __tablename__ = "learn_cycle_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    failures_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    clusters: Mapped[int] = mapped_column(Integer, default=0)
    recommendations_generated: Mapped[int] = mapped_column(Integer, default=0)
    recommendations_approved: Mapped[int] = mapped_column(Integer, default=0)
    recommendations_rejected: Mapped[int] = mapped_column(Integer, default=0)
    affected_components: Mapped[list] = mapped_column(JSON, default=list)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
