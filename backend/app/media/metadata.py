"""Temporal metadata assembly (Step 10) — pure computation over persisted counts.

Consolidates the numbers a `MediaJob` accumulates during processing into a single, future-facing
metadata dict that downstream modules (retrieval, context, dashboards) can consume directly without
re-querying every asset table. Kept pure (no ORM) so it is trivially unit-testable and reusable.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.media.models import PIPELINE_VERSION


def average_speech_rate(word_count: int, duration_ms: int) -> float | None:
    """Words per minute across the recording. None when duration is unknown."""
    if not duration_ms or duration_ms <= 0:
        return None
    minutes = duration_ms / 60_000.0
    if minutes <= 0:
        return None
    return round(word_count / minutes, 2)


def build_metadata(
    *,
    media_kind: str,
    media_category: str,
    language: str,
    duration_ms: int,
    width: int = 0,
    height: int = 0,
    fps: float | None = None,
    sample_rate: int = 0,
    channels: int = 0,
    video_codec: str = "",
    audio_codec: str = "",
    container: str = "",
    bitrate: int = 0,
    speaker_count: int = 0,
    scene_count: int = 0,
    frame_count: int = 0,
    subtitle_count: int = 0,
    segment_count: int = 0,
    ocr_frame_count: int = 0,
    chunk_count: int = 0,
    transcript_chars: int = 0,
    word_count: int = 0,
    transcription_confidence: float | None = None,
    processing_ms: int = 0,
    stage_latencies: Dict[str, int] | None = None,
    cache_hits: int = 0,
) -> Dict[str, Any]:
    """Return the canonical temporal-metadata dict for a processed recording."""
    return {
        "media_kind": media_kind,
        "media_category": media_category,
        "language": language,
        "duration_ms": duration_ms,
        "duration_readable": _readable(duration_ms),
        "video": {
            "width": width, "height": height, "fps": fps, "codec": video_codec,
        } if media_kind == "video" else None,
        "audio": {
            "sample_rate": sample_rate, "channels": channels, "codec": audio_codec,
        },
        "container": container,
        "bitrate": bitrate,
        "speaker_count": speaker_count,
        "scene_count": scene_count,
        "frame_count": frame_count,
        "subtitle_count": subtitle_count,
        "segment_count": segment_count,
        "ocr_frame_count": ocr_frame_count,
        "chunk_count": chunk_count,
        "transcript_length": transcript_chars,
        "word_count": word_count,
        "avg_speech_rate": average_speech_rate(word_count, duration_ms),
        "transcription_confidence": transcription_confidence,
        "processing_ms": processing_ms,
        "stage_latencies": stage_latencies or {},
        "cache_hits": cache_hits,
        "pipeline_version": PIPELINE_VERSION,
    }


def _readable(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"


def speaker_timeline(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order raw turns into a conversation timeline (Step 5). Pure; used by the API/service."""
    return sorted(
        [{"speaker_label": t.get("speaker_label", ""), "speaker_id": t.get("speaker_id"),
          "start_ms": int(t.get("start_ms", 0)), "end_ms": int(t.get("end_ms", 0))} for t in turns],
        key=lambda t: t["start_ms"],
    )
