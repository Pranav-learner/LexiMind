"""DTOs for the Knowledge Graph API (Phase 7, Module 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    """Ad-hoc extraction from raw text (developer / agent contribution)."""
    text: str = Field(min_length=1, max_length=100_000)
    document_id: Optional[str] = None
    source_type: str = "text"


class BuildRequest(BaseModel):
    force: bool = False


class GraphLogOut(BaseModel):
    id: str
    workspace_id: str
    document_id: Optional[str]
    scope: str
    status: str
    pipeline_version: str
    sources_processed: int
    chunks_processed: int
    entities_extracted: int
    entities_created: int
    entities_merged: int
    relationships_extracted: int
    relationships_created: int
    duplicates_merged: int
    validation_errors: int
    validation_warnings: int
    avg_confidence: float
    processing_ms: float
    error: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphLogDetailOut(GraphLogOut):
    report: Optional[Dict[str, Any]] = None


class EntityOut(BaseModel):
    id: str
    entity_type: str
    canonical_name: str
    normalized_name: str
    aliases: List[str]
    description: Optional[str]
    confidence: float
    mention_count: int
    degree: int
    source_refs: List[Dict[str, Any]]
    status: str
    version: int


class RelationshipOut(BaseModel):
    id: str
    rel_type: str
    directed: bool
    weight: float
    confidence: float
    mention_count: int
    source_id: str
    target_id: str
    source_name: Optional[str]
    target_name: Optional[str]
    evidence: List[Dict[str, Any]]
    version: int


class EntityDetailOut(EntityOut):
    relationships: List[RelationshipOut] = []


class GraphStatsOut(BaseModel):
    entities: int
    relationships: int
    merged_entities: int
    entity_types: Dict[str, int]
    relationship_types: Dict[str, int]
    density: float


class ValidationOut(BaseModel):
    ok: bool
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    error_count: int
    warning_count: int
    counts: Dict[str, int]
