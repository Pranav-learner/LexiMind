"""Multimodal ingestion domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class IngestionError(Exception):
    status_code = 400
    code = "ingestion_error"


class JobNotFound(IngestionError):
    status_code = 404
    code = "job_not_found"

    def __init__(self, job_id: str):
        super().__init__(f"Processing job '{job_id}' was not found.")


class DocumentNotFound(IngestionError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found in this workspace.")


class UnsupportedMedia(IngestionError):
    status_code = 415
    code = "unsupported_media"

    def __init__(self, media: str):
        super().__init__(f"Unsupported file type for multimodal processing: '{media}'.")


class IngestionStateError(IngestionError):
    """Illegal state transition (e.g. cancelling a completed job)."""

    status_code = 409
    code = "invalid_state"


class IngestionValidationError(IngestionError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
