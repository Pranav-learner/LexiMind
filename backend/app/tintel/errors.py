"""Temporal-intelligence domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class TemporalIntelError(Exception):
    status_code = 400
    code = "tintel_error"


class MediaNotFound(TemporalIntelError):
    status_code = 404
    code = "media_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Media '{document_id}' was not found in this workspace.")


class NotProcessed(TemporalIntelError):
    """Media exists but has no completed processing (nothing to derive intelligence from)."""

    status_code = 409
    code = "not_processed"

    def __init__(self, document_id: str):
        super().__init__(f"Media '{document_id}' has not finished processing yet.")
