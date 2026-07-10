"""Workspace domain errors (transport-agnostic).

Each carries an HTTP `status_code` and a short machine-readable `code`; the API layer maps
them to responses so business rules never import FastAPI.
"""

from __future__ import annotations


class WorkspaceError(Exception):
    status_code = 400
    code = "workspace_error"


class WorkspaceNotFound(WorkspaceError):
    status_code = 404
    code = "workspace_not_found"

    def __init__(self, workspace_id: str):
        super().__init__(f"Workspace '{workspace_id}' was not found.")


class DuplicateWorkspaceName(WorkspaceError):
    status_code = 409
    code = "duplicate_name"

    def __init__(self, name: str):
        super().__init__(f"You already have a workspace named '{name}'.")


class WorkspaceValidationError(WorkspaceError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class WorkspaceStateError(WorkspaceError):
    """Illegal state transition (e.g. restoring a workspace that isn't archived)."""

    status_code = 409
    code = "invalid_state"
