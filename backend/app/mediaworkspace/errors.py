"""Media AI Workspace domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class MediaWorkspaceError(Exception):
    status_code = 400
    code = "media_workspace_error"


class MediaNotFound(MediaWorkspaceError):
    status_code = 404
    code = "media_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Media '{document_id}' was not found in this workspace.")


class UnknownAction(MediaWorkspaceError):
    status_code = 422
    code = "unknown_action"

    def __init__(self, action: str):
        super().__init__(f"Unknown AI action '{action}'.")


class MediaWorkspaceValidationError(MediaWorkspaceError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
