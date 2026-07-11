"""Note DTOs + list query enums (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- create / update inputs
class NoteCreate(BaseModel):
    """Manual creation: blank note, PDF-selection note, or a chat/summary text paste.

    No AI runs on this path — the note is born `ready`. `citations` lets a caller (e.g. the
    "Save chat answer as note" action) carry the source message's citations along so provenance
    survives.
    """

    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    content: Optional[str] = None
    source: Optional[str] = None                     # blank|document|summary|chat|selection
    document_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tags: Optional[List[str]] = None                 # tag ids to attach
    citations: Optional[List["NoteCitationIn"]] = None


class NoteCitationIn(BaseModel):
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    page_number: Optional[int] = None
    citation_text: str = ""
    confidence: Optional[float] = None


class NoteGenerate(BaseModel):
    """AI creation: enqueues a note and generates structured, grounded sections."""

    note_type: str = Field(default="study")
    scope: Optional[str] = None                      # inferred from document ids if omitted
    document_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=300)
    subject: Optional[str] = None                    # focus hint for the LLM / default title


class NoteMetaUpdate(BaseModel):
    """Metadata-only patch (never touches `content` — autosave owns that)."""

    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_pinned: Optional[bool] = None
    is_favorite: Optional[bool] = None
    is_archived: Optional[bool] = None


class NoteContentUpdate(BaseModel):
    """Autosave payload. `base_version` enables optimistic-concurrency conflict detection."""

    content: str
    base_version: Optional[int] = None
    title: Optional[str] = Field(default=None, max_length=300)


class AssistRequest(BaseModel):
    """AI-assisted editing on a selection of note text."""

    operation: str                                   # see validation.ASSIST_OPS (in engine)
    selection: str
    instruction: Optional[str] = None                # optional extra guidance
    ground: bool = True                              # use retrieval for grounded ops


class AssistResponse(BaseModel):
    operation: str
    result: str


class TagCreate(BaseModel):
    name: str = Field(max_length=60)
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    color: Optional[str] = None


class NoteTagsUpdate(BaseModel):
    tag_ids: List[str]


# --------------------------------------------------------------------- output DTOs
class TagOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    color: str
    note_count: int

    model_config = {"from_attributes": True}


class NoteCitationOut(BaseModel):
    id: str
    note_section_id: Optional[str]
    document_id: Optional[str]
    chunk_id: Optional[str]
    page_number: Optional[int]
    workspace_id: str
    citation_text: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class NoteSectionOut(BaseModel):
    id: str
    heading: str
    order: int
    content: str
    citation_count: int

    model_config = {"from_attributes": True}


class OutlineItem(BaseModel):
    level: int
    text: str
    slug: str


class NoteOut(BaseModel):
    """List/summary view — no heavy `content`/sections, so grids stay light."""

    id: str
    workspace_id: str
    owner_id: str
    document_id: Optional[str]
    conversation_id: Optional[str]
    folder_id: Optional[str]
    source: str
    note_type: Optional[str]
    title: str
    description: str
    editor_format: str
    status: str
    progress: int
    stage: str
    error: Optional[str]
    created_by: str
    is_pinned: bool
    is_favorite: bool
    is_archived: bool
    word_count: int
    reading_time: int
    section_count: int
    citation_count: int
    model_name: str
    token_usage: int
    generation_ms: int
    version: int
    last_opened_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    tags: List[TagOut] = []

    model_config = {"from_attributes": True}


class NoteDetail(NoteOut):
    """Full view — includes editable `content`, the AI outline, citations, and derived outline."""

    content: str
    sections: List[NoteSectionOut] = []
    citations: List[NoteCitationOut] = []
    outline: List[OutlineItem] = []


class NoteListResponse(BaseModel):
    items: List[NoteOut]
    total: int
    page: int
    page_size: int
    pages: int


class TagListResponse(BaseModel):
    items: List[TagOut]
    total: int


# --------------------------------------------------------------------- list query enums
class SortField(str, Enum):
    created_at = "created_at"
    updated_at = "updated_at"
    last_opened_at = "last_opened_at"
    title = "title"
    word_count = "word_count"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class StatusFilter(str, Enum):
    any = "any"
    ready = "ready"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ArchivedFilter(str, Enum):
    active = "active"
    archived = "archived"
    all = "all"


class PinnedFilter(str, Enum):
    any = "any"
    pinned = "pinned"
    favorite = "favorite"


NoteCreate.model_rebuild()
