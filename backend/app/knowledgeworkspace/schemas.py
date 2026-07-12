"""DTOs for the Interactive Knowledge Workspace API (Phase 7, Module 4)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    hybrid: bool = False


class GraphChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    top_k: int = Field(default=12, ge=1, le=50)


class GraphChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: List[Dict[str, Any]] = []
    grounded: bool = False


class EditRequest(BaseModel):
    op: str = Field(pattern="^(rename_entity|edit_metadata|merge_entities|split_entity|delete_entity|"
                            "create_relationship|delete_relationship|approve_relationship|reject_relationship)$")
    params: Dict[str, Any] = {}
