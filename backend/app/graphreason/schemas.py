"""DTOs for the Graph Reasoning & Explainable AI API (Phase 7, Module 3)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReasonRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=3, ge=1, le=5)
    directed: bool = False
    verify: bool = True
    dependency: bool = False
    seed_entity_ids: Optional[List[str]] = None


class PreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=2, ge=1, le=5)


class RootCauseRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class ExplainRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=3, ge=1, le=5)


class ReasoningLogOut(BaseModel):
    id: str
    workspace_id: str
    query: str
    pipeline_version: str
    seed_count: int
    traversal_depth: int
    relationships_traversed: int
    paths_found: int
    inference_count: int
    dependency_chains: int
    root_causes: int
    reasoning_complexity: int
    cache_hit: bool
    overall_confidence: float
    confidence_band: str
    verification_status: str
    recognition_ms: float
    paths_ms: float
    inference_ms: float
    verification_ms: float
    confidence_ms: float
    total_ms: float
    created_at: datetime

    model_config = {"from_attributes": True}
