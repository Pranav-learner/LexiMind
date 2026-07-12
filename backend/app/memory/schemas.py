"""DTOs for the Semantic Memory & Graph Retrieval API (Phase 7, Module 2)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MemoryRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=2, ge=1, le=4)
    strategy: str = Field(default="bfs", pattern="^(bfs|dfs)$")
    rel_types: Optional[List[str]] = None
    max_nodes: int = Field(default=60, ge=1, le=500)
    limit: int = Field(default=20, ge=1, le=100)
    hybrid: bool = False
    seed_entity_ids: Optional[List[str]] = None


class RecognizeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class SyncRequest(BaseModel):
    document_id: Optional[str] = None
    force: bool = False


class SemanticMemoryLogOut(BaseModel):
    id: str
    workspace_id: str
    query: str
    mode: str
    seed_count: int
    traversal_depth: int
    traversal_strategy: str
    neighborhood_size: int
    edges_traversed: int
    hits_returned: int
    graph_hits: int
    vector_hits: int
    cache_hit: bool
    avg_confidence: float
    recognition_ms: float
    traversal_ms: float
    retrieval_ms: float
    fusion_ms: float
    context_ms: float
    total_ms: float
    created_at: datetime

    model_config = {"from_attributes": True}
