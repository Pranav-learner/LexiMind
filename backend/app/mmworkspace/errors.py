"""Multimodal workspace orchestrator errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class WorkspaceAIError(Exception):
    status_code = 400
    code = "workspace_ai_error"


class DocumentNotFound(WorkspaceAIError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found in this workspace.")


class UnknownAction(WorkspaceAIError):
    status_code = 422
    code = "unknown_action"

    def __init__(self, action: str):
        super().__init__(f"Unknown AI workspace action '{action}'.")
