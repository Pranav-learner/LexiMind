"""Field validation and normalization for documents.

Pure functions, no I/O — easy to unit test and reused by upload/rename paths. Raises
`DocumentValidationError`/`UnsupportedFileType`/`FileTooLarge` on bad input. Duplicate-file
detection is NOT here (it needs the repository); it lives in the service.
"""

from __future__ import annotations

import os
import re

from app.core.config import settings
from app.documents.errors import (
    DocumentValidationError,
    FileTooLarge,
    UnsupportedFileType,
)

DISPLAY_NAME_MAX_LEN = 300
DESCRIPTION_MAX_LEN = 4000

_FORBIDDEN_NAME_CHARS = set('/\\<>:"|?*')

# Map an extension to a coarse mime type. Kept tiny + offline; extend as media types land.
_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
}


def validate_display_name(raw: str | None, *, fallback: str) -> str:
    """Return a cleaned display name, defaulting to `fallback` (the filename) when empty."""
    if raw is None or raw.strip() == "":
        raw = fallback
    name = " ".join(raw.split())  # collapse internal whitespace, trim ends
    if len(name) < 1:
        raise DocumentValidationError("Document name cannot be empty.")
    if len(name) > DISPLAY_NAME_MAX_LEN:
        raise DocumentValidationError(
            f"Document name must be at most {DISPLAY_NAME_MAX_LEN} characters."
        )
    if any(ord(ch) < 32 for ch in name):
        raise DocumentValidationError("Document name contains invalid control characters.")
    bad = _FORBIDDEN_NAME_CHARS.intersection(name)
    if bad:
        chars = " ".join(sorted(bad))
        raise DocumentValidationError(f"Document name cannot contain: {chars}")
    return name


def validate_description(raw: str | None) -> str:
    if raw is None:
        return ""
    text = raw.strip()
    if len(text) > DESCRIPTION_MAX_LEN:
        raise DocumentValidationError(
            f"Description must be at most {DESCRIPTION_MAX_LEN} characters."
        )
    return text


def sanitize_filename(raw: str) -> str:
    """Strip path components and control/forbidden chars from an uploaded filename.

    Prevents path traversal (`../`) and keeps stored filenames filesystem-safe. Never returns
    an empty string.
    """
    base = os.path.basename(raw or "")
    base = "".join(ch for ch in base if ord(ch) >= 32)
    base = "".join(ch for ch in base if ch not in _FORBIDDEN_NAME_CHARS)
    base = base.strip().strip(".")
    return base or "untitled"


def file_extension(filename: str) -> str:
    """Lowercased extension without the dot (e.g. 'pdf'); '' when there is none."""
    _, ext = os.path.splitext(filename)
    return ext[1:].lower() if ext else ""


def validate_file_type(filename: str) -> str:
    """Return the validated lowercase extension or raise UnsupportedFileType."""
    ext = file_extension(filename)
    if ext not in settings.supported_document_extensions:
        raise UnsupportedFileType(ext or "unknown")
    return ext


def mime_for(ext: str) -> str:
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def validate_file_size(size: int) -> int:
    if size <= 0:
        raise DocumentValidationError("Uploaded file is empty.")
    if size > settings.max_upload_bytes:
        raise FileTooLarge(size, settings.max_upload_bytes)
    return size


def normalize_name_for_compare(name: str) -> str:
    """Case-insensitive key used for duplicate detection."""
    return " ".join(name.split()).casefold()


def guess_language(text: str) -> str:
    """Very small heuristic language guess (offline, no dependency).

    Returns 'en' when the sample is predominantly ASCII letters, else 'unknown'. A real
    langdetect model can replace this without touching the schema (see Lessons Learned).
    """
    sample = (text or "")[:2000]
    letters = [ch for ch in sample if ch.isalpha()]
    if not letters:
        return "unknown"
    ascii_letters = sum(1 for ch in letters if ord(ch) < 128)
    return "en" if ascii_letters / len(letters) > 0.9 else "unknown"


_WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))
