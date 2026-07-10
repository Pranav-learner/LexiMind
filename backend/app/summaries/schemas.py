"""Summary DTOs + list query enums."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SummaryCreate(BaseModel):
    summary_type: str = Field(default="standard")
    scope: Optional[str] = None                 # inferred from document_id/document_ids if omitted
    document_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    title: Optional[str] = Field(default=None, max_length=300)
    top_k: Optional[int] = None


class SummaryUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)


class SummaryCitationOut(BaseModel):
    id: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    page_number: Optional[int]
    workspace_id: str
    citation_text: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class SummarySectionOut(BaseModel):
    id: str
    heading: str
    order: int
    content: str
    citation_count: int
    citations: List[SummaryCitationOut] = []

    model_config = {"from_attributes": True}


class SummaryOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str
    scope: str
    document_id: Optional[str]
    document_ids: Optional[List[str]]
    conversation_id: Optional[str]
    title: str
    summary_type: str
    language: str
    status: str
    progress: int
    stage: str
    error: Optional[str]
    model_name: str
    prompt_version: str
    token_usage: int
    generation_ms: int
    section_count: int
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SummaryDetail(SummaryOut):
    sections: List[SummarySectionOut] = []


class SummaryListResponse(BaseModel):
    items: List[SummaryOut]
    total: int
    page: int
    page_size: int
    pages: int


class SortField(str, Enum):
    created_at = "created_at"
    updated_at = "updated_at"
    title = "title"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class StatusFilter(str, Enum):
    any = "any"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
