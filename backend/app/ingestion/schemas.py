"""Multimodal ingestion DTOs (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProcessRequest(BaseModel):
    force: bool = False   # reprocess even if a completed job for the same file hash exists


class ProcessingJobOut(BaseModel):
    id: str
    workspace_id: str
    document_id: str
    status: str
    stage: str
    progress: int
    error: Optional[str]
    attempts: int
    doc_type: str
    processing_type: str
    ocr_language: str
    ocr_confidence: Optional[float]
    page_count: int
    image_count: int
    table_count: int
    figure_count: int
    chunk_count: int
    ocr_pages: int
    processing_ms: int
    pipeline_version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractedImageOut(BaseModel):
    id: str
    page_number: int
    bbox: Optional[List[float]]
    width: int
    height: int
    image_type: str
    caption: Optional[str]
    confidence: Optional[float]
    hash: str

    model_config = {"from_attributes": True}


class ExtractedTableOut(BaseModel):
    id: str
    page_number: int
    bbox: Optional[List[float]]
    n_rows: int
    n_cols: int
    headers: Optional[List[Any]]
    cells: Optional[List[Any]]
    caption: Optional[str]

    model_config = {"from_attributes": True}


class ExtractedFigureOut(BaseModel):
    id: str
    page_number: int
    bbox: Optional[List[float]]
    figure_type: str
    caption: Optional[str]
    hash: str

    model_config = {"from_attributes": True}


class MultimodalChunkOut(BaseModel):
    id: str
    page_number: int
    chunk_type: str
    source: str
    chunk_index: int
    asset_id: Optional[str]
    bbox: Optional[List[float]]
    content: str
    meta: Optional[Dict[str, Any]]
    embedding_status: str

    model_config = {"from_attributes": True}


class ProcessingLogOut(BaseModel):
    stage: str
    level: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetsResponse(BaseModel):
    images: List[ExtractedImageOut] = []
    tables: List[ExtractedTableOut] = []
    figures: List[ExtractedFigureOut] = []


class JobDetail(ProcessingJobOut):
    logs: List[ProcessingLogOut] = []


class OcrPageOut(BaseModel):
    page_number: int
    text: str
    confidence: Optional[float]
    language: str
    cached: bool = False

    model_config = {"from_attributes": True}


class OcrStatusResponse(BaseModel):
    document_id: str
    ocr_pages: int
    language: str
    avg_confidence: Optional[float]
    pages: List[OcrPageOut] = []
