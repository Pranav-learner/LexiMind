"""Multimodal context domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class ContextError(Exception):
    status_code = 400
    code = "context_error"


class ContextValidationError(ContextError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
