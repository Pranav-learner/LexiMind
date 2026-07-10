"""Chat DTOs (Pydantic request/response contracts) + list query enums."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    document_scope: Optional[List[str]] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    model_name: Optional[str] = None


class ConversationUpdate(BaseModel):
    """Partial update — only provided fields change."""

    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    document_scope: Optional[List[str]] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    model_name: Optional[str] = None


class ConversationOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str
    title: str
    description: str
    is_pinned: bool
    is_archived: bool
    message_count: int
    last_message_at: Optional[datetime]
    document_scope: Optional[List[str]]
    temperature: float
    model_name: str
    system_prompt_version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: List[ConversationOut]
    total: int
    page: int
    page_size: int
    pages: int


class CitationOut(BaseModel):
    id: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    page_number: Optional[int]
    workspace_id: str
    citation_text: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    token_usage: int
    latency_ms: int
    retrieval_ms: int
    context_size: int
    citation_count: int
    meta: Optional[Dict[str, Any]] = Field(default=None, alias="meta")
    created_at: datetime
    citations: List[CitationOut] = []

    model_config = {"from_attributes": True, "populate_by_name": True}


class MessageListResponse(BaseModel):
    items: List[MessageOut]
    total: int
    page: int
    page_size: int
    pages: int


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    top_k: Optional[int] = None


class SortField(str, Enum):
    last_message_at = "last_message_at"
    created_at = "created_at"
    updated_at = "updated_at"
    title = "title"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ArchivedFilter(str, Enum):
    active = "active"
    archived = "archived"
    all = "all"


class PinnedFilter(str, Enum):
    any = "any"
    pinned = "pinned"
