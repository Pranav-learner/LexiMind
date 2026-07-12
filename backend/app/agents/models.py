"""Agent observability ORM (Step 11) — one telemetry table. NO business data.

`AgentExecutionLog` records how a run executed (plan, per-stage timings, retries, errors, token/cost
estimate, serialized execution graph + event timeline) — never the actual answer content or retrieved
documents. This is the single source for the execution-history + execution-log APIs and the debug
panel, consistent with every module owning one observability table (RetrievalLog / TemporalSearchLog /
MediaInteractionEvent).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # the execution_id (agx_…)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    agent: Mapped[str] = mapped_column(String(60), nullable=False, default="workspace_agent")

    query: Mapped[str] = mapped_column(Text, nullable=False, default="")   # the request text (not a result)
    conversation_id: Mapped[str | None] = mapped_column(String(40), default=None)
    document_id: Mapped[str | None] = mapped_column(String(40), default=None)

    # lifecycle
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="running")
    # running | completed | failed | cancelled
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    # plan + graph (serialized — telemetry, not business data)
    planner: Mapped[str] = mapped_column(String(40), nullable=False, default="heuristic-v1")
    requires_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    graph: Mapped[dict | None] = mapped_column(JSON, default=None)          # ExecutionPlan.to_dict()
    timeline: Mapped[list | None] = mapped_column(JSON, default=None)       # EventSink.timeline()

    # timings (ms)
    planner_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    selection_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tools_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # cost / usage estimates
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_agentlog_ws_created", "workspace_id", "created_at"),
        Index("ix_agentlog_owner", "owner_id", "workspace_id"),
    )
