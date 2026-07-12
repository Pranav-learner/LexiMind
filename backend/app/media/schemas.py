"""Media DTOs (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProcessRequest(BaseModel):
    force: bool = False   # reprocess even if a completed job for the same file hash exists


class MediaJobOut(BaseModel):
    id: str
    workspace_id: str
    document_id: str
    status: str
    stage: str
    progress: int
    error: Optional[str]
    attempts: int
    media_kind: str
    media_category: str
    category_confidence: Optional[float]
    language: str
    duration_ms: int
    width: int
    height: int
    fps: Optional[float]
    sample_rate: int
    channels: int
    video_codec: str
    audio_codec: str
    container: str
    bitrate: int
    speaker_count: int
    scene_count: int
    frame_count: int
    subtitle_count: int
    segment_count: int
    ocr_frame_count: int
    chunk_count: int
    transcript_chars: int
    word_count: int
    avg_speech_rate: Optional[float]
    transcription_confidence: Optional[float]
    processing_ms: int
    pipeline_version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MediaProcessingLogOut(BaseModel):
    stage: str
    level: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaJobDetail(MediaJobOut):
    logs: List[MediaProcessingLogOut] = []


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    media_kind: str
    job: MediaJobOut


class TranscriptSegmentOut(BaseModel):
    id: str
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    speaker_id: Optional[str]
    speaker_label: str
    confidence: Optional[float]
    language: str

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    document_id: str
    language: str
    segment_count: int
    duration_ms: int
    segments: List[TranscriptSegmentOut] = []


class SpeakerOut(BaseModel):
    id: str
    speaker_label: str
    display_name: Optional[str]
    total_speaking_ms: int
    turn_count: int
    segment_count: int
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class SpeakerTurnOut(BaseModel):
    speaker_id: Optional[str]
    speaker_label: str
    turn_index: int
    start_ms: int
    end_ms: int

    model_config = {"from_attributes": True}


class SpeakerTimelineResponse(BaseModel):
    document_id: str
    speaker_count: int
    speakers: List[SpeakerOut] = []
    timeline: List[SpeakerTurnOut] = []


class MediaFrameOut(BaseModel):
    id: str
    frame_index: int
    timestamp_ms: int
    scene_id: Optional[str]
    scene_index: Optional[int]
    width: int
    height: int
    hash: str
    is_keyframe: bool
    extraction: str
    ocr_text: Optional[str]
    ocr_confidence: Optional[float]

    model_config = {"from_attributes": True}


class SceneOut(BaseModel):
    id: str
    scene_index: int
    start_ms: int
    end_ms: int
    duration_ms: int
    score: Optional[float]
    representative_frame_id: Optional[str]

    model_config = {"from_attributes": True}


class SubtitleOut(BaseModel):
    id: str
    subtitle_index: int
    start_ms: int
    end_ms: int
    text: str
    source: str
    language: str

    model_config = {"from_attributes": True}


class MediaChunkOut(BaseModel):
    id: str
    chunk_type: str
    source: str
    chunk_index: int
    start_ms: int
    end_ms: int
    speaker_id: Optional[str]
    scene_id: Optional[str]
    asset_id: Optional[str]
    content: str
    meta: Optional[Dict[str, Any]]
    embedding_status: str

    model_config = {"from_attributes": True}


class OcrFrameOut(BaseModel):
    id: str
    frame_index: int
    timestamp_ms: int
    ocr_text: str
    ocr_confidence: Optional[float]

    model_config = {"from_attributes": True}


class OcrResponse(BaseModel):
    document_id: str
    ocr_frame_count: int
    frames: List[OcrFrameOut] = []
