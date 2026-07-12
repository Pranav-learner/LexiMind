"""Temporal retrieval domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class TemporalRetrievalError(Exception):
    status_code = 400
    code = "temporal_retrieval_error"


class TemporalValidationError(TemporalRetrievalError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
