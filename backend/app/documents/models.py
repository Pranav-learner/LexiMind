"""Document ORM model — Phase 3, Module 2.

A Document is a first-class knowledge asset inside a workspace. Where Module 1 gave every
chunk a `workspace_id`, this model gives every *uploaded file* a durable, structured identity:
its lifecycle (processing/indexing status), its derived statistics (pages, words, chunks),
and its link to the vector layer.

Two-store design (unchanged from Module 1): structured rows live in SQLite; vectors live in
FAISS + `vector_metadata.json`. The link between a Document row and its chunks is the string
`vector_document_id` — the same value written into every chunk's `metadata["document_id"]`
at ingest time. This keeps the relational layer decoupled from FAISS: to count/delete/reindex
a document's chunks we filter chunk metadata by `(vector_document_id, workspace_id)`.

Scalability / indexing rationale:
- `workspace_id` and `owner_id` are indexed — every list query scopes by them.
- `is_archived` is indexed — the library splits active vs archived.
- `vector_document_id` is indexed — chunk-level operations look documents up by it.
- (`workspace_id`, `filename`) composite index — duplicate-file detection + lookups.
- Soft delete via `deleted_at` (nullable): reversible unless a caller asks for a hard delete.

Future multimodal support (images / audio / video / web pages) is why `media_type`,
`mime_type`, and `file_type` are separate columns and why the status columns are free-form
strings rather than a PDF-specific boolean: a future extractor sets `ocr_status`,
`summary_status`, etc. without a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return f"doc_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_uuid)

    # --- ownership / scoping (indexed: every list filters by these) ---
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # Link to the vector layer: equals every chunk's metadata["document_id"].
    vector_document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # --- identity ---
    filename: Mapped[str] = mapped_column(String(500), nullable=False)      # physical/original name
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)  # user-facing (renamable)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- file facts ---
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="document")  # future: image/audio/video/webpage
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")           # e.g. "pdf"
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)               # bytes
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    # --- derived statistics (filled during processing) ---
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    # --- embedding provenance ---
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- lifecycle status (free-form strings so future stages need no migration) ---
    processing_status: Mapped[str] = mapped_column(String(30), index=True, nullable=False, default="uploaded")
    processing_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="uploaded")
    processing_error: Mapped[str | None] = mapped_column(Text, default=None)
    processing_ms: Mapped[int | None] = mapped_column(Integer, default=None)   # processing duration
    upload_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..100
    indexing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    summary_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    ocr_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")

    # --- state / soft delete ---
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- timestamps ---
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        # Duplicate-file detection + per-workspace filename lookups.
        Index("ix_documents_ws_filename", "workspace_id", "filename"),
        # Chunk-level ops resolve a document by (workspace, vector id).
        Index("ix_documents_ws_vector", "workspace_id", "vector_document_id"),
    )
