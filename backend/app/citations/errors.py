"""Citation-intelligence domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class CitationError(Exception):
    status_code = 400
    code = "citation_error"


class CitationNotFound(CitationError):
    status_code = 404
    code = "citation_not_found"

    def __init__(self, citation_id: str):
        super().__init__(f"Citation '{citation_id}' was not found.")


class CitationValidationError(CitationError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
