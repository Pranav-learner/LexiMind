"""Semantic memory domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class MemoryError(Exception):
    status_code = 400
    code = "memory_error"


class EntityNotFound(MemoryError):
    status_code = 404
    code = "entity_not_found"

    def __init__(self, entity_id: str):
        super().__init__(f"Entity '{entity_id}' was not found in the graph.")
