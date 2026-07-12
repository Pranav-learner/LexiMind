"""Audio/Video media ORM — Phase 5, Module 1: Audio & Video Processing Engine.

Nine NEW tables. This is a SEPARATE async layer attached to an existing `Document` row (created by
the media-upload path with `media_type` in {audio, video}) — the analogue of Phase-4's
`ProcessingJob` layer for PDFs/images, but for TEMPORAL knowledge. It never touches the Phase-1 text
retrieval pipeline; its job is to turn a raw recording into timestamp-aware structured knowledge
(transcript, speakers, scenes, frames, subtitles, frame-OCR) that FUTURE modules can retrieve.

- `MediaJob`          — one async media-processing job per document. Holds media classification,
                        container/codec facts, temporal metadata + counters, per-stage latencies
                        (observability), and progress. Resumable via `completed_stages`.
- `TranscriptSegment` — one speech-to-text segment: [start_ms, end_ms) text, speaker, confidence,
                        optional word-level timings. The atomic unit of temporal transcript retrieval.
- `Speaker`           — a diarized speaker (label, speaking duration, turn count). Future speaker
                        identification maps `display_name` onto a persistent identity.
- `SpeakerTurn`       — one contiguous speaking turn (conversation timeline).
- `MediaFrame`        — an extracted representative frame (timestamp, size, hash, stored file,
                        keyframe flag, optional per-frame OCR text). Future vision-analysis input.
- `Scene`             — a detected scene boundary [start_ms, end_ms) with a representative frame.
                        Future retrieval treats scenes as independent knowledge units.
- `Subtitle`          — an embedded/closed-caption/generated subtitle cue.
- `MediaChunk`        — a UNIFIED temporal chunk (transcript|speaker|scene|subtitle|ocr|frame).
                        `embedding_status="pending"` is the FUTURE embedding queue — nothing is
                        embedded into FAISS in this module (mirrors MultimodalChunk).
- `MediaProcessingLog`— a per-stage processing log line (progress / observability).

Frame OCR is CACHED in the Phase-4 `OcrResult` table (keyed by document + content hash), reusing the
existing cache rather than duplicating one. `pipeline_version` lets future changes re-process only
stale media.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PIPELINE_VERSION = "media-v1"


def _now() -> datetime:
    # Naive UTC to match SQLite's tz-stripped reads (project-wide convention since Module 7).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _job_id() -> str:
    return f"mediajob_{uuid.uuid4().hex[:14]}"


def _asset_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class MediaJob(Base):
    __tablename__ = "media_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_job_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    file_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")  # skip unchanged reprocess

    # Async lifecycle.
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="queued")
    # queued | processing | completed | failed | cancelled
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..100
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_stages: Mapped[list | None] = mapped_column(JSON, default=None)  # resumable bookkeeping

    # Classification (Step 3).
    media_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="audio")   # audio | video
    media_category: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    category_confidence: Mapped[float | None] = mapped_column(Float, default=None)

    # Container / codec facts + temporal metadata (Step 2/10).
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fps: Mapped[float | None] = mapped_column(Float, default=None)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_codec: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    audio_codec: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    container: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    bitrate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Extraction counters (Step 10 metadata).
    speaker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scene_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtitle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transcript_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_speech_rate: Mapped[float | None] = mapped_column(Float, default=None)  # words / minute
    transcription_confidence: Mapped[float | None] = mapped_column(Float, default=None)

    # Per-stage latencies (Step 16 observability).
    transcribe_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diarize_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenes_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtitles_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    processing_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default=PIPELINE_VERSION)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_mediajobs_ws_doc", "workspace_id", "document_id"),
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("seg"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaker_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    speaker_label: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    no_speech_prob: Mapped[float | None] = mapped_column(Float, default=None)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    words: Mapped[list | None] = mapped_column(JSON, default=None)  # [[word, start_ms, end_ms, conf], ...]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_segments_doc_start", "document_id", "start_ms"),
    )


class Speaker(Base):
    __tablename__ = "media_speakers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("spk"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    speaker_label: Mapped[str] = mapped_column(String(40), nullable=False, default="")   # SPEAKER_00
    display_name: Mapped[str | None] = mapped_column(String(120), default=None)          # future identification
    total_speaking_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_speakers_doc", "document_id"),
    )


class SpeakerTurn(Base):
    __tablename__ = "speaker_turns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("turn"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    speaker_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    speaker_label: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_turns_doc_start", "document_id", "start_ms"),
    )


class MediaFrame(Base):
    __tablename__ = "media_frames"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("frm"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    frame_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scene_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    scene_index: Mapped[int | None] = mapped_column(Integer, default=None)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")  # dedup
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    is_keyframe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extraction: Mapped[str] = mapped_column(String(20), nullable=False, default="periodic")  # periodic|scene|keyframe|thumbnail
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None)          # on-screen text (Step 8)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_frames_doc_ts", "document_id", "timestamp_ms"),
    )


class Scene(Base):
    __tablename__ = "media_scenes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("scn"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    scene_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float | None] = mapped_column(Float, default=None)                  # boundary strength
    representative_frame_id: Mapped[str | None] = mapped_column(String(40), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_scenes_doc_start", "document_id", "start_ms"),
    )


class Subtitle(Base):
    __tablename__ = "media_subtitles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("sub"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    subtitle_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="embedded")  # embedded|caption|generated
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_subtitles_doc_start", "document_id", "start_ms"),
    )


class MediaChunk(Base):
    __tablename__ = "media_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("mck"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    chunk_type: Mapped[str] = mapped_column(String(20), nullable=False, default="transcript")
    # transcript | speaker | scene | subtitle | ocr | frame
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="asr")  # asr|diarizer|scenedet|subtitle|ocr|frame
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    speaker_id: Mapped[str | None] = mapped_column(String(40), default=None)
    scene_id: Mapped[str | None] = mapped_column(String(40), default=None)
    asset_id: Mapped[str | None] = mapped_column(String(40), default=None)  # frame/subtitle/segment id
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=None)

    # FUTURE embedding queue — nothing is embedded into FAISS in this module.
    embedding_status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="pending")
    embedding_model: Mapped[str | None] = mapped_column(String(120), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_mediachunks_doc_type", "document_id", "chunk_type"),
        Index("ix_mediachunks_doc_start", "document_id", "start_ms"),
        Index("ix_mediachunks_embed", "embedding_status"),
    )


class MediaProcessingLog(Base):
    __tablename__ = "media_processing_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _asset_id("mlog"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="info")  # info|warn|error
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
