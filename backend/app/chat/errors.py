"""Chat domain errors (transport-agnostic).

Each carries an HTTP `status_code` + machine `code`; the API maps them to responses so business
rules never import FastAPI. Mirrors the workspace/document error modules.
"""

from __future__ import annotations


class ChatError(Exception):
    status_code = 400
    code = "chat_error"


class ConversationNotFound(ChatError):
    status_code = 404
    code = "conversation_not_found"

    def __init__(self, conversation_id: str):
        super().__init__(f"Conversation '{conversation_id}' was not found.")


class ChatValidationError(ChatError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class ConversationStateError(ChatError):
    """Illegal state transition (e.g. restoring a conversation that isn't archived)."""

    status_code = 409
    code = "invalid_state"
