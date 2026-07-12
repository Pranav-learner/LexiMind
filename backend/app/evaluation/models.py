"""AI Evaluation ORM (Phase 8, Module 1) — golden datasets + reproducible run telemetry.

Three tables, workspace-scoped:
- `EvalDataset`      — a versioned golden dataset (name/version/tags/item_count).
- `EvalItem`        — one golden item (question + ground truth + relevant chunks/entities + expected
                      citations + difficulty), the unit a benchmark scores against.
- `EvaluationRunLog`— one reproducible benchmark run (pipeline+version, dataset+version, model, the full
                      metric set, cost/latency, regression status, CI gate). Stores the report so a run
                      can be re-read without re-executing. NEVER duplicates production telemetry.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # ds_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    tags: Mapped[list | None] = mapped_column(JSON, default=None)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty_distribution: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (Index("ix_evds_ws_name", "workspace_id", "name"),)


class EvalItem(Base):
    __tablename__ = "eval_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # item_…
    dataset_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, default=None)
    ground_truth: Mapped[str | None] = mapped_column(Text, default=None)
    relevant_document_ids: Mapped[list | None] = mapped_column(JSON, default=None)
    relevant_chunk_ids: Mapped[list | None] = mapped_column(JSON, default=None)
    relevant_entities: Mapped[list | None] = mapped_column(JSON, default=None)
    expected_citations: Mapped[list | None] = mapped_column(JSON, default=None)
    expected_relationships: Mapped[list | None] = mapped_column(JSON, default=None)
    difficulty: Mapped[str] = mapped_column(String(12), nullable=False, default="medium")   # easy|medium|hard
    tags: Mapped[list | None] = mapped_column(JSON, default=None)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (Index("ix_evit_dataset", "dataset_id"),)


class EvaluationRunLog(Base):
    __tablename__ = "evaluation_run_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # evr_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    dataset_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pipeline: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    model: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    label: Mapped[str | None] = mapped_column(String(120), default=None)

    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="completed")
    metrics: Mapped[dict | None] = mapped_column(JSON, default=None)          # aggregate metric -> value
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    judge_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # regression + CI
    baseline_run_id: Mapped[str | None] = mapped_column(String(40), default=None)
    regression_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    # none | improved | stable | regressed
    gate_passed: Mapped[bool | None] = mapped_column(Boolean, default=None)

    report: Mapped[dict | None] = mapped_column(JSON, default=None)   # per-item + judgments + regression detail
    error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_evrun_ws_created", "workspace_id", "created_at"),
        Index("ix_evrun_ds_pipeline", "dataset_id", "pipeline"),
    )
