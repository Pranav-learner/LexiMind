"""Document DTOs (Pydantic request/response contracts) and list query params.

DTOs are the wire contract, decoupled from the ORM model so the API shape and storage schema
evolve independently. `DocumentOut.model_validate(row)` maps an ORM row to the response.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --- status vocabularies (documented, not DB-enforced, so future stages need no migration) ---
class ProcessingStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class IndexingStatus(str, Enum):
    pending = "pending"
    indexed = "indexed"
    stale = "stale"       # re-index needed (e.g. after a config change)
    failed = "failed"


# Ordered lifecycle stages surfaced to the UI (Uploaded → … → Ready).
PROCESSING_STAGES = (
    "uploaded",
    "text_extraction",
    "chunking",
    "embedding",
    "faiss_indexing",
    "bm25_indexing",
    "metadata",
    "ready",
)


class DocumentUpdate(BaseModel):
    """Partial update — only provided fields change. Physical file is never renamed."""

    display_name: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)


class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str
    vector_document_id: str

    filename: str
    display_name: str
    description: str

    media_type: str
    file_type: str
    mime_type: str
    file_size: int

    page_count: int
    word_count: int
    chunk_count: int
    language: str

    embedding_model: str
    embedding_dimension: int

    processing_status: str
    processing_stage: str
    processing_error: Optional[str]
    processing_ms: Optional[int]
    upload_progress: int
    indexing_status: str
    summary_status: str
    ocr_status: str

    is_archived: bool
    last_indexed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IndexHealth(BaseModel):
    """Live, cross-store view of a document's presence in the retrieval indexes."""

    chunk_count: int          # rows in the vector metadata for this document
    embedding_count: int      # vectors in FAISS attributable to this document (== chunk_count)
    faiss_status: str         # "indexed" | "missing" | "unknown"
    bm25_status: str          # "indexed" | "missing" | "unknown"
    index_health: str         # "healthy" | "degraded" | "empty"


class DocumentDetail(DocumentOut):
    """Details view = the document row plus a live index-health probe."""

    index_health: Optional[IndexHealth] = None


class DocumentListResponse(BaseModel):
    items: List[DocumentOut]
    total: int
    page: int
    page_size: int
    pages: int


class UploadItemResult(BaseModel):
    """Per-file outcome of a (possibly multi-file) upload request."""

    filename: str
    success: bool
    document: Optional[DocumentOut] = None
    error: Optional[str] = None


class UploadResponse(BaseModel):
    uploaded: int
    failed: int
    items: List[UploadItemResult]


# --- Module 3: PDF Viewer DTOs ---
class ChunkOut(BaseModel):
    """One indexed chunk of a document, exposed for citation highlighting + outline."""

    chunk_id: str
    document_id: Optional[str]
    page_number: Optional[int]
    section: Optional[str]
    chunk_index: Optional[int]
    text: str


class DocumentChunksResponse(BaseModel):
    document_id: str
    vector_document_id: str
    total: int
    items: List[ChunkOut]


class ReadingProgressUpdate(BaseModel):
    page: int = Field(ge=1)
    scroll_top: int = Field(default=0, ge=0)
    zoom: int = Field(default=100, ge=10, le=1000)
    rotation: int = Field(default=0)


class ReadingSessionOut(BaseModel):
    id: str
    workspace_id: str
    document_id: str
    page: int
    scroll_top: int
    zoom: int
    rotation: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadingHistoryItem(BaseModel):
    """A recently-viewed document = its reading session joined with document display fields."""

    document_id: str
    display_name: str
    filename: str
    file_type: str
    page: int
    page_count: int
    updated_at: datetime


class ReadingHistoryResponse(BaseModel):
    items: List[ReadingHistoryItem]


class SortField(str, Enum):
    display_name = "display_name"   # alphabetical
    created_at = "created_at"       # newest / oldest
    file_size = "file_size"
    page_count = "page_count"
    last_indexed_at = "last_indexed_at"  # recently indexed
    updated_at = "updated_at"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ArchivedFilter(str, Enum):
    active = "active"      # not archived (default)
    archived = "archived"  # archived only
    all = "all"            # both


class IndexedFilter(str, Enum):
    any = "any"            # no constraint (default)
    indexed = "indexed"    # indexing_status == indexed
    unindexed = "unindexed"
