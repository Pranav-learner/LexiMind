"""Graph reasoning domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class ReasoningError(Exception):
    status_code = 400
    code = "reasoning_error"


class EntityNotFound(ReasoningError):
    status_code = 404
    code = "entity_not_found"

    def __init__(self, entity_id: str):
        super().__init__(f"Entity '{entity_id}' was not found in the graph.")


class ReasoningLogNotFound(ReasoningError):
    status_code = 404
    code = "reasoning_log_not_found"

    def __init__(self, log_id: str):
        super().__init__(f"Reasoning log '{log_id}' was not found.")
