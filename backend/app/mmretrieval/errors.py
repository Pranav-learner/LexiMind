"""Multimodal retrieval domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class RetrievalError(Exception):
    status_code = 400
    code = "retrieval_error"


class RetrievalValidationError(RetrievalError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
