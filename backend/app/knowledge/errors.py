"""Knowledge-graph domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class GraphError(Exception):
    status_code = 400
    code = "graph_error"


class EntityNotFound(GraphError):
    status_code = 404
    code = "entity_not_found"

    def __init__(self, entity_id: str):
        super().__init__(f"Entity '{entity_id}' was not found.")


class RelationshipNotFound(GraphError):
    status_code = 404
    code = "relationship_not_found"

    def __init__(self, rel_id: str):
        super().__init__(f"Relationship '{rel_id}' was not found.")


class DocumentNotFound(GraphError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found.")


class GraphLogNotFound(GraphError):
    status_code = 404
    code = "graph_log_not_found"

    def __init__(self, log_id: str):
        super().__init__(f"Graph construction log '{log_id}' was not found.")
