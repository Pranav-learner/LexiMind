"""Multimodal workspace DTOs — the unified surfaces (ingest, assets, timeline, pipeline, actions)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- unified ingest
class IngestItemResult(BaseModel):
    filename: str
    success: bool
    error: Optional[str] = None
    document_id: Optional[str] = None
    display_name: Optional[str] = None
    processing_job_id: Optional[str] = None    # Module-1 multimodal processing
    vision_job_id: Optional[str] = None        # Module-2 vision analysis
    media_kind: Optional[str] = None           # pdf | image


class IngestResponse(BaseModel):
    uploaded: int
    failed: int
    items: List[IngestItemResult]


# --------------------------------------------------------------------- asset explorer
class AssetItem(BaseModel):
    id: str
    asset_type: str            # document | image | diagram | table | figure | summary | note | deck | conversation
    modality: str              # text | image | diagram | table | figure | mixed
    title: str
    subtitle: str = ""
    document_id: Optional[str] = None
    page_number: Optional[int] = None
    created_at: Optional[str] = None
    route: Optional[str] = None
    thumbnail_url: Optional[str] = None
    metadata: Dict[str, Any] = {}


class AssetExplorerResponse(BaseModel):
    items: List[AssetItem]
    total: int
    counts: Dict[str, int]     # per asset_type


# --------------------------------------------------------------------- timeline
class TimelineEvent(BaseModel):
    type: str
    icon: str
    title: str
    timestamp: Optional[str]
    route: Optional[str] = None
    target_id: Optional[str] = None


class TimelineResponse(BaseModel):
    items: List[TimelineEvent]


# --------------------------------------------------------------------- pipeline status
class PipelineStatus(BaseModel):
    document_id: str
    display_name: str
    text_indexed: bool
    processing: Optional[Dict[str, Any]] = None   # Module-1 job summary
    vision: Optional[Dict[str, Any]] = None       # Module-2 job summary
    counts: Dict[str, int]                        # ocr_pages, images, tables, figures, chunks, vision_assets
    ready: bool                                   # all pipelines complete


# --------------------------------------------------------------------- AI workspace actions
class AiActionRequest(BaseModel):
    action: str                                   # summary | notes | flashcards
    document_id: str
    focus: Optional[str] = None                   # e.g. "diagrams", "tables", "screenshots"
    count: Optional[int] = Field(default=None, ge=1, le=60)


class AiActionResponse(BaseModel):
    action: str
    asset_type: str            # summary | note | deck
    asset_id: str
    status: str
    route: str


# --------------------------------------------------------------------- overview / observability
class WorkspaceOverview(BaseModel):
    workspace_id: str
    name: str
    assets: Dict[str, int]     # documents, images, diagrams, tables, figures, summaries, notes, decks, chats
    modalities: Dict[str, int]  # text_chunks, ocr_pages, vision_assets, vision_embeddings
    pipelines: Dict[str, int]  # processed_documents, vision_analyzed, pending_embeddings
    activity: Dict[str, int]   # searches, context_builds
    ready_documents: int
