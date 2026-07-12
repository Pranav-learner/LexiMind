"""Audio/Video media domain errors (transport-agnostic — each carries a `status_code`).

Mirrors `app.ingestion.errors`: the service raises these; the API layer maps `status_code`
to HTTP. Nothing here imports FastAPI, so the domain stays framework-agnostic.
"""

from __future__ import annotations


class MediaError(Exception):
    status_code = 400
    code = "media_error"


class MediaJobNotFound(MediaError):
    status_code = 404
    code = "media_job_not_found"

    def __init__(self, job_id: str):
        super().__init__(f"Media job '{job_id}' was not found.")


class MediaNotFound(MediaError):
    status_code = 404
    code = "media_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Media asset '{document_id}' was not found in this workspace.")


class UnsupportedMedia(MediaError):
    status_code = 415
    code = "unsupported_media"

    def __init__(self, media: str):
        super().__init__(f"Unsupported media type for audio/video processing: '{media}'.")


class MediaTooLarge(MediaError):
    status_code = 413
    code = "media_too_large"

    def __init__(self, size: int, limit: int):
        super().__init__(f"Media file is {size} bytes; the limit is {limit} bytes.")


class MediaStateError(MediaError):
    """Illegal state transition (e.g. cancelling a completed job)."""

    status_code = 409
    code = "invalid_state"


class MediaValidationError(MediaError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
