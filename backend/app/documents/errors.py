"""Document domain errors (transport-agnostic).

Each carries an HTTP `status_code` and a short machine-readable `code`; the API layer maps
them to responses so business rules never import FastAPI. Mirrors the workspace error module.
"""

from __future__ import annotations


class DocumentError(Exception):
    status_code = 400
    code = "document_error"


class DocumentNotFound(DocumentError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found.")


class DuplicateDocument(DocumentError):
    status_code = 409
    code = "duplicate_document"

    def __init__(self, filename: str):
        super().__init__(f"A document named '{filename}' already exists in this workspace.")


class DocumentValidationError(DocumentError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class UnsupportedFileType(DocumentError):
    status_code = 415
    code = "unsupported_file_type"

    def __init__(self, ext: str):
        super().__init__(f"Unsupported file type: '{ext}'.")


class FileTooLarge(DocumentError):
    status_code = 413
    code = "file_too_large"

    def __init__(self, size: int, limit: int):
        super().__init__(
            f"File is {size} bytes; the maximum allowed is {limit} bytes."
        )


class DocumentStateError(DocumentError):
    """Illegal state transition (e.g. restoring a document that isn't archived)."""

    status_code = 409
    code = "invalid_state"
