"""Pure validation for summaries."""

from __future__ import annotations

from app.summaries.errors import SummaryValidationError

TITLE_MAX_LEN = 300

# Supported summary types → their coarse intent. Architecture allows future custom templates by
# adding an entry here + a prompt/plan in the engine.
SUMMARY_TYPES = ("quick", "standard", "detailed", "bullet", "chapterwise")
SCOPES = ("document", "multi", "workspace")


def validate_title(raw: str | None, *, default: str) -> str:
    if raw is None or raw.strip() == "":
        return default
    title = " ".join(raw.split())
    if len(title) > TITLE_MAX_LEN:
        raise SummaryValidationError(f"Title must be at most {TITLE_MAX_LEN} characters.")
    if any(ord(ch) < 32 for ch in title):
        raise SummaryValidationError("Title contains invalid control characters.")
    return title


def validate_summary_type(raw: str | None) -> str:
    t = (raw or "standard").strip().lower()
    if t not in SUMMARY_TYPES:
        raise SummaryValidationError(
            f"Unknown summary type '{raw}'. Supported: {', '.join(SUMMARY_TYPES)}."
        )
    return t


def validate_scope(scope: str | None, *, document_id: str | None, document_ids: list | None) -> str:
    s = (scope or "").strip().lower()
    if not s:
        # Infer from what was provided.
        if document_ids:
            s = "multi"
        elif document_id:
            s = "document"
        else:
            s = "workspace"
    if s not in SCOPES:
        raise SummaryValidationError(f"Unknown scope '{scope}'. Supported: {', '.join(SCOPES)}.")
    if s == "document" and not document_id:
        raise SummaryValidationError("A 'document' summary requires document_id.")
    if s == "multi" and not document_ids:
        raise SummaryValidationError("A 'multi' summary requires document_ids.")
    return s


def default_title(summary_type: str, *, scope: str, subject: str | None = None) -> str:
    label = {
        "quick": "Quick summary",
        "standard": "Summary",
        "detailed": "Detailed summary",
        "bullet": "Bullet summary",
        "chapterwise": "Chapter-wise summary",
    }.get(summary_type, "Summary")
    if subject:
        return f"{label}: {subject}"[:TITLE_MAX_LEN]
    if scope == "workspace":
        return f"{label} (workspace)"
    return label
