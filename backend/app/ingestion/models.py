"""Multimodal ingestion ORM — Phase 4, Module 1: Multimodal Document Processing Engine.

Seven NEW tables. This is a SEPARATE async layer attached to an existing `Document` (created by the
Phase-3 upload path) — it never modifies the text upload→chunk→embed→retrieval pipeline, so Phase-1
retrieval is untouched. Its job is to turn any uploaded file (native/scanned/mixed PDF, image,
screenshot, photo) into structured multimodal knowledge for FUTURE multimodal embeddings & retrieval.

- `ProcessingJob`   — one async multimodal-processing job per document. Also holds the document
                      classification (doc_type/processing_type) + extraction counters + progress.
- `OcrResult`       — per-page OCR output, CACHED by content hash so OCR is never re-run needlessly.
- `ExtractedImage`  — an embedded/extracted image (page, bbox, size, type, hash, stored file).
- `ExtractedTable`  — a detected table (page, bbox, headers, cells).
- `ExtractedFigure` — a detected figure/diagram/chart (page, bbox, type, caption, hash).
- `MultimodalChunk` — a unified chunk (text|ocr|image|table|figure). `embedding_status="pending"`
                      is the FUTURE embedding queue — nothing is embedded into FAISS yet.
- `ProcessingLog`   — a per-stage processing log line (progress/observability).

Backward compatibility: existing text chunks live in FAISS as before; MultimodalChunk is additive
and does not enter the retrieval index in this module. `pipeline_version` lets future changes
re-process only stale documents.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PIPELINE_VERSION = "mm-v1"


def _now() -> datetime:
    # Naive UTC to match SQLite's tz-stripped reads (project-wide convention since Module 7).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _job_id() -> str:
    return f"mmjob_{uuid.uuid4().hex[:16]}"


def _asset_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_job_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    file_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")  # skip unchanged reprocessing

    # Async lifecycle.
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="queued")
    # queued | processing | completed | failed | cancelled
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..100
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_stages: Mapped[list | None] = mapped_column(JSON, default=None)  # resumable bookkeeping

    # Classification (Step 3).
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    # text_pdf | scanned_pdf | mixed_pdf | image | screenshot | photo | unknown
    processing_type: Mapped[str] = mapped_column(String(20), nullable=False, default="native")
    # native | ocr | mixed | image_only
    ocr_language: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, default=None)

    # Extraction counters (Step 9 metadata).
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    figure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    processing_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default=PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_mmjobs_ws_doc", "workspace_id", "document_id"),
    )


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("ocr"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    boxes: Mapped[list | None] = mapped_column(JSON, default=None)          # [[x0,y0,x1,y1,text,conf], ...]
    reading_order: Mapped[list | None] = mapped_column(JSON, default=None)  # ordering of boxes/paragraphs

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        # The cache key: never re-OCR the same page content twice.
        UniqueConstraint("document_id", "page_number", "content_hash", name="uq_ocr_cache"),
        Index("ix_ocr_doc", "document_id"),
    )


class ExtractedImage(Base):
    __tablename__ = "extracted_images"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("img"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bbox: Mapped[list | None] = mapped_column(JSON, default=None)  # [x0,y0,x1,y1]
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_type: Mapped[str] = mapped_column(String(20), nullable=False, default="raster")  # raster|photo|screenshot|icon
    caption: Mapped[str | None] = mapped_column(Text, default=None)  # future vision-caption
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")  # dedup
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtractedTable(Base):
    __tablename__ = "extracted_tables"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("tbl"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bbox: Mapped[list | None] = mapped_column(JSON, default=None)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    headers: Mapped[list | None] = mapped_column(JSON, default=None)
    cells: Mapped[list | None] = mapped_column(JSON, default=None)   # [[...row...], ...]
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")  # CSV export (future)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtractedFigure(Base):
    __tablename__ = "extracted_figures"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("fig"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bbox: Mapped[list | None] = mapped_column(JSON, default=None)
    figure_type: Mapped[str] = mapped_column(String(20), nullable=False, default="figure")  # figure|diagram|chart|flowchart|equation
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class MultimodalChunk(Base):
    __tablename__ = "multimodal_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("mmck"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")  # text|ocr|image|table|figure
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="native")     # native|ocr|extractor
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_id: Mapped[str | None] = mapped_column(String(40), default=None)  # link to image/table/figure
    bbox: Mapped[list | None] = mapped_column(JSON, default=None)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")   # text, OCR text, or a descriptor
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=None)

    # FUTURE embedding queue — nothing is embedded into FAISS in this module.
    embedding_status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="pending")
    embedding_model: Mapped[str | None] = mapped_column(String(120), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_mmchunks_doc_type", "document_id", "chunk_type"),
        Index("ix_mmchunks_embed", "embedding_status"),
    )


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("log"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="info")  # info|warn|error
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
