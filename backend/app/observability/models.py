"""Observability ORM (Phase 8, Module 2) — distributed tracing + alerting.

This module UNIFIES existing telemetry (RetrievalLog / AgentExecutionLog / VerificationLog / …) by
READING it (see unifier.py) — it never re-persists it. The only NEW persistence here is:
- `Trace` / `Span` — cross-cutting per-request distributed traces (parent-child spans) that the existing
  per-module logs cannot express (they are siloed telemetry).
- `AlertRule` / `AlertEvent` — configurable alert thresholds + fired alerts.

Traces are written ASYNCHRONOUSLY at request end (one batched commit) so instrumentation never slows the
hot path (Step 13).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Trace(Base):
    __tablename__ = "obs_traces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # trc_… (the trace id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    operation: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="request")
    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False, default="ok")   # ok | error
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    span_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attributes: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_trace_ws_created", "workspace_id", "created_at"),)


class Span(Base):
    __tablename__ = "obs_spans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # spn_…
    trace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    component: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="")
    start_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)   # offset from trace start
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ok")
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attributes: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_span_trace", "trace_id"),)


class AlertRule(Base):
    __tablename__ = "obs_alert_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # alr_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(60), nullable=False)     # e.g. p95_latency_ms | error_rate | total_cost
    comparator: Mapped[str] = mapped_column(String(4), nullable=False, default="gt")   # gt | lt
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="warning")   # info|warning|critical
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channels: Mapped[list | None] = mapped_column(JSON, default=None)   # future: slack/webhook/email

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_alertrule_ws", "workspace_id"),)


class AlertEvent(Base):
    __tablename__ = "obs_alert_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # ale_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="warning")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_alertevent_ws_created", "workspace_id", "created_at"),)
