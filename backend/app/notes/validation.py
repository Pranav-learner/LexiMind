"""Pure validation + small text helpers for notes (no I/O, no ORM)."""

from __future__ import annotations

import re

from app.notes.errors import NoteValidationError

TITLE_MAX_LEN = 300
DESCRIPTION_MAX_LEN = 2000
CONTENT_MAX_LEN = 500_000          # ~500 KB of Markdown — long-form but bounded (perf guard).
TAG_NAME_MAX_LEN = 60
WORDS_PER_MINUTE = 200             # standard reading-speed estimate.

# AI note templates. Architecture allows future CUSTOM templates by adding an entry here plus a
# plan/prompt in the engine — nothing else in the stack hard-codes the list.
NOTE_TYPES = ("quick", "study", "detailed", "chapterwise", "concept", "revision")
# How a note was created. Every path funnels through the same Note model.
SOURCES = ("blank", "document", "summary", "chat", "selection")
SCOPES = ("document", "multi", "workspace")

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def validate_title(raw: str | None, *, default: str) -> str:
    if raw is None or raw.strip() == "":
        return default
    title = " ".join(raw.split())
    if len(title) > TITLE_MAX_LEN:
        raise NoteValidationError(f"Title must be at most {TITLE_MAX_LEN} characters.")
    if any(ord(ch) < 32 for ch in title):
        raise NoteValidationError("Title contains invalid control characters.")
    return title


def validate_description(raw: str | None) -> str:
    if not raw:
        return ""
    desc = raw.strip()
    if len(desc) > DESCRIPTION_MAX_LEN:
        raise NoteValidationError(f"Description must be at most {DESCRIPTION_MAX_LEN} characters.")
    return desc


def validate_content(raw: str | None) -> str:
    content = raw or ""
    if len(content) > CONTENT_MAX_LEN:
        raise NoteValidationError(
            f"Note content is too large ({len(content)} chars; max {CONTENT_MAX_LEN})."
        )
    return content


def validate_note_type(raw: str | None) -> str:
    t = (raw or "study").strip().lower()
    if t not in NOTE_TYPES:
        raise NoteValidationError(
            f"Unknown note type '{raw}'. Supported: {', '.join(NOTE_TYPES)}."
        )
    return t


def validate_scope(scope: str | None, *, document_id: str | None, document_ids: list | None) -> str:
    s = (scope or "").strip().lower()
    if not s:
        if document_ids:
            s = "multi"
        elif document_id:
            s = "document"
        else:
            s = "workspace"
    if s not in SCOPES:
        raise NoteValidationError(f"Unknown scope '{scope}'. Supported: {', '.join(SCOPES)}.")
    if s == "document" and not document_id:
        raise NoteValidationError("A 'document' note requires document_id.")
    if s == "multi" and not document_ids:
        raise NoteValidationError("A 'multi' note requires document_ids.")
    return s


def validate_tag_name(raw: str | None) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise NoteValidationError("Tag name cannot be empty.")
    if len(name) > TAG_NAME_MAX_LEN:
        raise NoteValidationError(f"Tag name must be at most {TAG_NAME_MAX_LEN} characters.")
    return name


def validate_color(raw: str | None, *, default: str = "#6366f1") -> str:
    if not raw:
        return default
    color = raw.strip()
    if not _HEX_COLOR.match(color):
        raise NoteValidationError("Color must be a hex value like #6366f1.")
    return color


def normalize_tag_for_compare(name: str) -> str:
    return " ".join(name.split()).casefold()


def default_note_title(note_type: str | None, *, source: str, subject: str | None = None) -> str:
    if subject:
        subject = subject.strip()
    if source == "blank":
        return "Untitled note"
    label = {
        "quick": "Quick notes",
        "study": "Study notes",
        "detailed": "Detailed notes",
        "chapterwise": "Chapter notes",
        "concept": "Concept notes",
        "revision": "Revision notes",
    }.get(note_type or "", "Notes")
    if subject:
        return f"{label}: {subject}"[:TITLE_MAX_LEN]
    return label


# --- text metrics (used by the service on every content write) --------------------------------
def word_count(content: str) -> int:
    """Count words in Markdown, ignoring fenced code and heading/list markers well enough for a
    reading estimate. Cheap and deterministic — recomputed on autosave."""
    if not content:
        return 0
    # Strip fenced code blocks so code doesn't inflate the estimate.
    text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
    return len(re.findall(r"[A-Za-z0-9']+", text))


def reading_minutes(words: int) -> int:
    if words <= 0:
        return 0
    return max(1, round(words / WORDS_PER_MINUTE))


def outline_from_markdown(content: str, *, max_items: int = 200) -> list[dict]:
    """Derive a live outline from a note's Markdown headings.

    Returns [{level, text, slug}] in document order. The UI renders this so the outline stays
    correct after edits (the stored NoteSection rows are only the AI's original structure).
    """
    items: list[dict] = []
    in_fence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            items.append({"level": level, "text": text, "slug": slug})
            if len(items) >= max_items:
                break
    return items
