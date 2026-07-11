"""Vision Intelligence ORM — Phase 4, Module 2: Vision Intelligence Engine.

Three NEW tables. This module *understands* the visual assets Module 1 extracted
(`ExtractedImage`/`ExtractedFigure`/`ExtractedTable`) — it does not re-extract them. It adds a
classification + caption + structured metadata + separate vision embeddings for each asset, turning
raw images into structured semantic knowledge.

- `VisionJob`       — one async vision-analysis job per document (status/stage/progress/counts/logs).
- `VisionAnalysis`  — per visual asset: classification, semantic caption, detected objects +
                      relationships, structured understanding (diagram nodes/edges, chart axes/series,
                      table schema, screenshot components), keywords/topics/complexity/confidence.
- `VisionEmbedding` — the vision vector, stored SEPARATELY from text embeddings (per spec) behind a
                      model-family abstraction (clip | siglip | fake), so the embedding model can be
                      swapped without touching consumers.

Compatibility: nothing here enters the FAISS text index (retrieval unchanged). Captions are written
back to the Module-1 asset rows (the `caption` columns reserved for exactly this), and the analyzed
asset's `MultimodalChunk` is enriched — all still `embedding_status="pending"` (the future
multimodal-retrieval queue). `pipeline_version` lets future changes re-analyze only stale assets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

VISION_PIPELINE_VERSION = "vis-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class VisionJob(Base):
    __tablename__ = "vision_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("visjob"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="queued")
    # queued | processing | completed | failed | cancelled
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    asset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    model_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    processing_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default=VISION_PIPELINE_VERSION)
    logs: Mapped[list | None] = mapped_column(JSON, default=None)  # [{stage, level, message}]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (Index("ix_visjobs_ws_doc", "workspace_id", "document_id"),)


class VisionAnalysis(Base):
    __tablename__ = "vision_analyses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("vis"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)   # image | figure | table
    asset_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Classification (Step 3): architecture_diagram|flowchart|er_diagram|uml|pie_chart|bar_chart|
    # line_chart|scatter_plot|table|code_screenshot|ui_screenshot|scientific_figure|general_image
    image_type: Mapped[str] = mapped_column(String(40), nullable=False, default="general_image")
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")            # semantic caption (Step 4)

    objects: Mapped[list | None] = mapped_column(JSON, default=None)                  # detected objects
    relationships: Mapped[list | None] = mapped_column(JSON, default=None)            # edges/relations
    structured: Mapped[dict | None] = mapped_column(JSON, default=None)               # diagram/chart/table/screenshot schema
    keywords: Mapped[list | None] = mapped_column(JSON, default=None)
    topics: Mapped[list | None] = mapped_column(JSON, default=None)

    complexity: Mapped[str] = mapped_column(String(10), nullable=False, default="low")  # low|medium|high
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    thumbnail_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    processing_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default=VISION_PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        # One analysis per asset (re-analysis replaces it).
        UniqueConstraint("asset_type", "asset_id", name="uq_vision_asset"),
        Index("ix_vision_doc_type", "document_id", "image_type"),
    )


class VisionEmbedding(Base):
    __tablename__ = "vision_embeddings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("vemb"))
    analysis_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    model_family: Mapped[str] = mapped_column(String(20), nullable=False, default="fake")  # clip|siglip|fake
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector: Mapped[list | None] = mapped_column(JSON, default=None)  # stored separately from text embeddings

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_type", "asset_id", "model", name="uq_vision_embedding"),
        Index("ix_vemb_doc", "document_id"),
    )
