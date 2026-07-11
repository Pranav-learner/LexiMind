"""Vision Intelligence DTOs (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class VisionProcessRequest(BaseModel):
    force: bool = False   # re-analyze even if a completed job exists


class VisionJobOut(BaseModel):
    id: str
    workspace_id: str
    document_id: str
    status: str
    stage: str
    progress: int
    error: Optional[str]
    attempts: int
    asset_count: int
    analyzed_count: int
    embedding_count: int
    model_name: str
    embedding_model: str
    processing_ms: int
    pipeline_version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VisionJobDetail(VisionJobOut):
    logs: List[Dict[str, Any]] = []


class VisionAnalysisOut(BaseModel):
    id: str
    asset_type: str
    asset_id: str
    page_number: int
    image_type: str
    caption: str
    objects: Optional[List[Any]]
    relationships: Optional[List[Any]]
    structured: Optional[Dict[str, Any]]
    keywords: Optional[List[str]]
    topics: Optional[List[str]]
    complexity: str
    confidence: Optional[float]
    language: str
    has_embedding: bool = False

    model_config = {"from_attributes": True}


class VisionAnalysisList(BaseModel):
    items: List[VisionAnalysisOut]
    total: int


class VisionEmbeddingOut(BaseModel):
    id: str
    asset_type: str
    asset_id: str
    model: str
    model_family: str
    dim: int
    # The vector itself is only returned when explicitly requested (it can be large).
    vector: Optional[List[float]] = None

    model_config = {"from_attributes": True}


class CaptionOut(BaseModel):
    asset_id: str
    asset_type: str
    image_type: str
    caption: str
    confidence: Optional[float]


class SearchMetaItem(BaseModel):
    """A lightweight visual-knowledge index entry (for future visual search)."""

    analysis_id: str
    document_id: str
    asset_type: str
    asset_id: str
    image_type: str
    caption: str
    keywords: List[str] = []
    page_number: int
    confidence: Optional[float]


class SearchMetaResponse(BaseModel):
    items: List[SearchMetaItem]
    total: int
