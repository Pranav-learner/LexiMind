"""Workspace DTOs (Pydantic request/response contracts) and list query params.

DTOs are the wire contract; they are deliberately decoupled from the ORM model so the API
shape and storage schema can evolve independently. `WorkspaceOut.model_validate(row)` maps
an ORM row to the response.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    icon: Optional[str] = None
    color: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    """All fields optional — only provided fields are changed (partial update)."""

    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    icon: Optional[str] = None
    color: Optional[str] = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    color: str
    owner_id: str
    is_archived: bool
    document_count: int
    chat_count: int
    note_count: int
    flashcard_count: int
    summary_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceListResponse(BaseModel):
    items: List[WorkspaceOut]
    total: int
    page: int
    page_size: int
    pages: int


class SortField(str, Enum):
    name = "name"
    created_at = "created_at"
    updated_at = "updated_at"
    document_count = "document_count"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ArchivedFilter(str, Enum):
    active = "active"      # not archived (default)
    archived = "archived"  # archived only
    all = "all"            # both
