"""Summary domain errors (transport-agnostic)."""

from __future__ import annotations


class SummaryError(Exception):
    status_code = 400
    code = "summary_error"


class SummaryNotFound(SummaryError):
    status_code = 404
    code = "summary_not_found"

    def __init__(self, summary_id: str):
        super().__init__(f"Summary '{summary_id}' was not found.")


class SummaryValidationError(SummaryError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class SummaryStateError(SummaryError):
    """Illegal state transition (e.g. cancelling a completed summary)."""

    status_code = 409
    code = "invalid_state"
