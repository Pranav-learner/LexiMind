"""Pure validation + format registry for audio/video ingestion (no I/O, no ORM).

This is the single source of truth for which containers we accept and how a file extension maps
to a media *kind* (audio vs video). It is intentionally self-contained (it does NOT touch
`app.documents.validation`, which is pdf-only) so extending media support never risks the text
upload path. Adding a codec later is a one-line change here plus a branch in the engine.
"""

from __future__ import annotations

from app.core.config import settings
from app.media.errors import MediaTooLarge, MediaValidationError, UnsupportedMedia

# ---- accepted containers, grouped by kind ----------------------------------------------------
AUDIO_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "aac": "audio/aac",
}
VIDEO_TYPES = {
    "mp4": "video/mp4",
    "mkv": "video/x-matroska",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "webm": "video/webm",
}

# Declared but NOT processed yet — kept here so the registry is the single source of truth and
# turning them on later is additive (a new import source, not a schema change).
FUTURE_SOURCES = {"youtube", "livestream", "stream", "s3", "gcs", "url"}

SUPPORTED_TYPES = {**AUDIO_TYPES, **VIDEO_TYPES}

# Enumerations reused by schemas + classification.
MEDIA_KINDS = ("audio", "video")
MEDIA_CATEGORIES = (
    "lecture", "meeting", "podcast", "tutorial", "interview",
    "presentation", "screen_recording", "conference_talk", "voice_memo", "webinar", "unknown",
)
CHUNK_TYPES = ("transcript", "speaker", "scene", "subtitle", "ocr", "frame")
SUBTITLE_SOURCES = ("embedded", "caption", "generated")
FRAME_EXTRACTIONS = ("periodic", "scene", "keyframe", "thumbnail")


def normalize_ext(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").strip().lower()


def is_audio(ext: str) -> bool:
    return ext.strip().lower() in AUDIO_TYPES


def is_video(ext: str) -> bool:
    return ext.strip().lower() in VIDEO_TYPES


def media_kind(ext: str) -> str:
    """Return 'audio' | 'video' for a supported extension (validate first)."""
    e = ext.strip().lower()
    if e in AUDIO_TYPES:
        return "audio"
    if e in VIDEO_TYPES:
        return "video"
    return "unknown"


def validate_supported(ext: str) -> str:
    """Ensure a file type can be processed by the media engine (415 otherwise)."""
    e = ext.strip().lower()
    if e in FUTURE_SOURCES:
        raise UnsupportedMedia(f"{e} (planned import source, not yet supported)")
    if e not in SUPPORTED_TYPES:
        raise UnsupportedMedia(e or "unknown")
    return e


def validate_size(size: int) -> int:
    """Reject empty / oversize uploads cheaply, before any disk or transcription work."""
    if size <= 0:
        raise MediaValidationError("Uploaded media file is empty.")
    if size > settings.max_media_bytes:
        raise MediaTooLarge(size, settings.max_media_bytes)
    return size


def validate_duration(duration_ms: int | None) -> None:
    """Guard against absurd durations (corrupt metadata). 0/None is allowed (unknown)."""
    if duration_ms is None:
        return
    if duration_ms < 0:
        raise MediaValidationError("Media duration cannot be negative.")
    if duration_ms > settings.max_media_duration_ms:
        raise MediaValidationError(
            f"Media duration {duration_ms} ms exceeds the limit of {settings.max_media_duration_ms} ms."
        )


def mime_for(ext: str) -> str:
    return SUPPORTED_TYPES.get(ext.strip().lower(), "application/octet-stream")
