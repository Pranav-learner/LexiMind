"""Analytics domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class AnalyticsError(Exception):
    status_code = 400
    code = "analytics_error"


class DocumentNotFound(AnalyticsError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found in this workspace.")


class UnknownSection(AnalyticsError):
    status_code = 404
    code = "unknown_section"

    def __init__(self, section: str):
        super().__init__(f"Unknown dashboard section '{section}'.")
