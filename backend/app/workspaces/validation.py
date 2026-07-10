"""Field validation and normalization for workspaces.

Pure functions, no I/O — easy to unit test and reused by both create and update paths.
Raises `WorkspaceValidationError` with a human-meaningful message on bad input. Duplicate-
name detection is NOT here (it needs the repository); it lives in the service.
"""

from __future__ import annotations

import re

from app.workspaces.errors import WorkspaceValidationError

NAME_MIN_LEN = 1
NAME_MAX_LEN = 120
DESCRIPTION_MAX_LEN = 2000
ICON_MAX_LEN = 40

# Names may contain letters (any language), digits, spaces, and a small punctuation set.
# We forbid control characters and path/markup-dangerous characters (/ \ < > : " | ? *).
_FORBIDDEN_NAME_CHARS = set('/\\<>:"|?*')
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def validate_name(raw: str) -> str:
    """Return a cleaned workspace name or raise WorkspaceValidationError."""
    if raw is None:
        raise WorkspaceValidationError("Workspace name is required.")
    name = " ".join(raw.split())  # collapse internal whitespace, trim ends
    if len(name) < NAME_MIN_LEN:
        raise WorkspaceValidationError("Workspace name cannot be empty.")
    if len(name) > NAME_MAX_LEN:
        raise WorkspaceValidationError(f"Workspace name must be at most {NAME_MAX_LEN} characters.")
    if any(ord(ch) < 32 for ch in name):
        raise WorkspaceValidationError("Workspace name contains invalid control characters.")
    bad = _FORBIDDEN_NAME_CHARS.intersection(name)
    if bad:
        chars = " ".join(sorted(bad))
        raise WorkspaceValidationError(f"Workspace name cannot contain: {chars}")
    return name


def validate_description(raw: str | None) -> str:
    if raw is None:
        return ""
    text = raw.strip()
    if len(text) > DESCRIPTION_MAX_LEN:
        raise WorkspaceValidationError(
            f"Description must be at most {DESCRIPTION_MAX_LEN} characters."
        )
    return text


def validate_color(raw: str | None, *, default: str = "#6366f1") -> str:
    if raw is None or raw.strip() == "":
        return default
    color = raw.strip()
    if not _HEX_COLOR_RE.match(color):
        raise WorkspaceValidationError("Color must be a hex value like #6366f1.")
    return color.lower()


def validate_icon(raw: str | None, *, default: str = "📁") -> str:
    if raw is None or raw.strip() == "":
        return default
    icon = raw.strip()
    if len(icon) > ICON_MAX_LEN:
        raise WorkspaceValidationError(f"Icon must be at most {ICON_MAX_LEN} characters.")
    return icon


def normalize_name_for_compare(name: str) -> str:
    """Case-insensitive key used for duplicate detection."""
    return " ".join(name.split()).casefold()
