"""ORM models for Optimization & Cost Intelligence (Phase 8, Module 3).

`OptimizationRunLog` (Step 11) — the optimization decision + estimated-vs-actual cost + savings + policy
version, per applied run. This is NEW telemetry that no existing `*Log` expresses (retrieval/agent/etc. logs
record execution, not the optimization decision that shaped it). `WorkspacePolicy` persists the per-workspace
policy selection (Step 15).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OptimizationRunLog(Base):
    __tablename__ = "opt_run_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    policy: Mapped[str] = mapped_column(String(40), default="balanced")
    policy_version: Mapped[str] = mapped_column(String(40), default="policy-v1")
    tier: Mapped[str] = mapped_column(String(20), default="moderate")
    model_selected: Mapped[str] = mapped_column(String(80), default="")
    retrieval_policy: Mapped[str] = mapped_column(Text, default="")   # JSON string
    compression: Mapped[str] = mapped_column(String(20), default="none")
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    cache_used: Mapped[bool] = mapped_column(default=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_cost: Mapped[float] = mapped_column(Float, default=0.0)
    savings: Mapped[float] = mapped_column(Float, default=0.0)        # fraction 0..1
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    quality_impact: Mapped[float] = mapped_column(Float, default=0.0)  # verification confidence proxy
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkspacePolicy(Base):
    __tablename__ = "opt_workspace_policies"

    workspace_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    policy: Mapped[str] = mapped_column(String(40), default="balanced")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
