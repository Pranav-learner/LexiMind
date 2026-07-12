"""Knowledge Workspace domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class WorkspaceError(Exception):
    status_code = 400
    code = "knowledge_workspace_error"


class EntityNotFound(WorkspaceError):
    status_code = 404
    code = "entity_not_found"

    def __init__(self, entity_id: str):
        super().__init__(f"Entity '{entity_id}' was not found.")


class RelationshipNotFound(WorkspaceError):
    status_code = 404
    code = "relationship_not_found"

    def __init__(self, rel_id: str):
        super().__init__(f"Relationship '{rel_id}' was not found.")


class InvalidEdit(WorkspaceError):
    status_code = 422
    code = "invalid_edit"
