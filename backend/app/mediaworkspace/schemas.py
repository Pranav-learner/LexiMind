"""Media AI Workspace DTOs (Pydantic)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- media chat
class MediaChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None     # continue an existing media conversation
    document_id: Optional[str] = None          # scope the chat to one recording
    top_k: int = Field(default=12, ge=1, le=50)


class MediaCitationOut(BaseModel):
    index: Optional[int] = None
    document_id: Optional[str]
    modality: Optional[str] = None
    start_ms: int = 0
    end_ms: int = 0
    timespan: str = ""
    speaker_label: str = ""
    scene_id: Optional[str] = None
    frame_id: Optional[str] = None
    text: str = ""


class MediaChatResponse(BaseModel):
    ok: bool
    conversation_id: str
    document_id: Optional[str]
    answer: str
    grounded: bool
    citations: List[MediaCitationOut] = []
    primary: Optional[str] = None
    retrieval_ms: int = 0
    latency_ms: int = 0
    context_size: int = 0
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None


# --------------------------------------------------------------------- timeline
class TimelineItem(BaseModel):
    kind: str                                  # chapter | topic | event | speaker | scene
    id: str
    title: str
    start_ms: int
    end_ms: int
    timespan: str
    lane: str                                  # which timeline lane to render on
    metadata: Dict[str, Any] = {}


class TimelineResponse(BaseModel):
    document_id: str
    duration_ms: int
    items: List[TimelineItem] = []
    lanes: List[str] = []


# --------------------------------------------------------------------- playback / library / overview
class PlaybackMetaResponse(BaseModel):
    document_id: str
    media_kind: str
    duration_ms: int
    media_url: str
    chapters: int
    speakers: int
    scenes: int
    processing_status: str


class MediaLibraryItem(BaseModel):
    document_id: str
    display_name: str
    media_kind: str
    duration_ms: int
    processing_status: str
    intelligence_ready: bool
    speaker_count: int
    chapter_count: int
    created_at: Optional[str]


class MediaLibraryResponse(BaseModel):
    items: List[MediaLibraryItem] = []
    total: int


class OverviewResponse(BaseModel):
    workspace_id: str
    recordings: int
    audio: int
    video: int
    total_duration_ms: int
    transcript_segments: int
    speakers: int
    chapters: int
    topics: int
    events: int
    scenes: int
    frames: int
    temporal_searches: int
    media_chats: int
    interactions: Dict[str, int] = {}


# --------------------------------------------------------------------- AI actions
class AiActionRequest(BaseModel):
    action: str                                # summary|notes|flashcards|study_guide|revision|minutes|action_items|key_decisions
    document_id: str
    focus: Optional[str] = None                # e.g. a chapter title / topic
    count: Optional[int] = Field(default=None, ge=1, le=50)


class AiActionResponse(BaseModel):
    action: str
    asset_type: str
    asset_id: str
    status: str
    route: str


# --------------------------------------------------------------------- unified search
class MediaSearchResponse(BaseModel):
    query: str
    total: int
    temporal: List[Dict[str, Any]] = []
    documents: List[Dict[str, Any]] = []
    total_ms: float = 0.0


# --------------------------------------------------------------------- observability
class InteractionRequest(BaseModel):
    event_type: str
    document_id: Optional[str] = None
    target: Optional[str] = None
    position_ms: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None


class ObservabilityResponse(BaseModel):
    workspace_id: str
    usage: Dict[str, int]
    total: int
    recent: List[Dict[str, Any]] = []
