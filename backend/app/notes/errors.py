"""Note domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class NoteError(Exception):
    status_code = 400
    code = "note_error"


class NoteNotFound(NoteError):
    status_code = 404
    code = "note_not_found"

    def __init__(self, note_id: str):
        super().__init__(f"Note '{note_id}' was not found.")


class TagNotFound(NoteError):
    status_code = 404
    code = "tag_not_found"

    def __init__(self, tag_id: str):
        super().__init__(f"Tag '{tag_id}' was not found.")


class SourceNotFound(NoteError):
    """A conversion source (summary/message) could not be resolved."""

    status_code = 404
    code = "source_not_found"


class NoteValidationError(NoteError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class DuplicateTagName(NoteError):
    status_code = 409
    code = "duplicate_tag"

    def __init__(self, name: str):
        super().__init__(f"A tag named '{name}' already exists in this workspace.")


class NoteStateError(NoteError):
    """Illegal state transition (e.g. cancelling a ready note)."""

    status_code = 409
    code = "invalid_state"


class NoteConflict(NoteError):
    """Optimistic-concurrency conflict: the client's base version is stale."""

    status_code = 409
    code = "version_conflict"

    def __init__(self, expected: int, got: int):
        super().__init__(
            f"This note was modified elsewhere (server version {expected}, your base {got}). "
            "Reload to get the latest content before saving."
        )
        self.expected = expected
        self.got = got
