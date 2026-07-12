"""Orchestration observability ORM (Step 11) — one telemetry table for multi-agent runs.

`OrchestrationExecutionLog` records how a workflow of agents ran (the task graph with per-node status,
execution order, parallel width, retries/failures/recovered, per-stage timings, LLM calls + cost, and
the message timeline) AND stores the aggregated deliverable + final verification so the dashboard can
render a run without re-executing. It NEVER duplicates AgentExecutionLog / AgentTaskLog /
VerificationLog — those own per-agent + per-verification telemetry; this owns the ORCHESTRATION layer
(each node still writes its own AgentTaskLog via the reused per-agent pathway).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrchestrationExecutionLog(Base):
    __tablename__ = "orchestration_execution_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # orc_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow: Mapped[str] = mapped_column(String(60), nullable=False, default="custom")
    planner: Mapped[str] = mapped_column(String(40), nullable=False, default="heuristic-v1")

    # lifecycle
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="running")
    # running | completed | partial | failed | cancelled

    # graph + telemetry
    graph: Mapped[dict | None] = mapped_column(JSON, default=None)          # TaskGraph.to_dict() w/ statuses
    agents_used: Mapped[list | None] = mapped_column(JSON, default=None)
    messages: Mapped[list | None] = mapped_column(JSON, default=None)        # communication-bus timeline
    node_results: Mapped[list | None] = mapped_column(JSON, default=None)

    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parallel_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovered_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # per-stage timings (ms)
    planner_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    schedule_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    aggregate_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # aggregated deliverable + trust
    output: Mapped[dict | None] = mapped_column(JSON, default=None)          # unified StructuredOutput
    final_verification: Mapped[dict | None] = mapped_column(JSON, default=None)
    verification_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unknown")
    verification_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_orclog_ws_created", "workspace_id", "created_at"),
        Index("ix_orclog_owner", "owner_id", "workspace_id"),
    )
