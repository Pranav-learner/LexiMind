"""Pure validation/normalization for chat (no I/O)."""

from __future__ import annotations

from app.chat.errors import ChatValidationError

TITLE_MAX_LEN = 300
DESCRIPTION_MAX_LEN = 2000
MESSAGE_MAX_LEN = 32000  # generous upper bound guarding against pathological payloads

DEFAULT_TITLE = "New chat"


def validate_title(raw: str | None, *, default: str = DEFAULT_TITLE) -> str:
    if raw is None or raw.strip() == "":
        return default
    title = " ".join(raw.split())
    if len(title) > TITLE_MAX_LEN:
        raise ChatValidationError(f"Title must be at most {TITLE_MAX_LEN} characters.")
    if any(ord(ch) < 32 for ch in title):
        raise ChatValidationError("Title contains invalid control characters.")
    return title


def validate_description(raw: str | None) -> str:
    if raw is None:
        return ""
    text = raw.strip()
    if len(text) > DESCRIPTION_MAX_LEN:
        raise ChatValidationError(f"Description must be at most {DESCRIPTION_MAX_LEN} characters.")
    return text


def validate_message_content(raw: str | None) -> str:
    if raw is None or raw.strip() == "":
        raise ChatValidationError("Message content cannot be empty.")
    text = raw.strip()
    if len(text) > MESSAGE_MAX_LEN:
        raise ChatValidationError(f"Message is too long (max {MESSAGE_MAX_LEN} characters).")
    return text


def title_from_message(content: str, *, max_len: int = 60) -> str:
    """Auto-generate a conversation title from the first user message.

    Single line, trimmed, capped — remains user-editable afterwards.
    """
    first_line = " ".join((content or "").split())
    if not first_line:
        return DEFAULT_TITLE
    if len(first_line) <= max_len:
        return first_line
    return first_line[:max_len].rstrip() + "…"
