"""Pure validation for flashcards/decks (no I/O, no ORM)."""

from __future__ import annotations

import re

from app.flashcards.errors import FlashcardValidationError

DECK_NAME_MAX = 200
DESCRIPTION_MAX = 2000
FRONT_MAX = 4000
BACK_MAX = 8000
HINT_MAX = 1000

# Card types. `mixed` is a generation preference (let the LLM choose); the others are real card
# types. multiple_choice/image/diagram are reserved for future modules (architecture-ready).
CARD_TYPES = ("basic", "definition", "cloze", "truefalse")
CARD_TYPE_PREFS = ("mixed", *CARD_TYPES)
RESERVED_CARD_TYPES = ("multiple_choice", "image", "diagram")

SCOPES = ("manual", "document", "multi", "workspace")
DIFFICULTIES = ("easy", "medium", "hard")
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Max cards a single AI generation job will produce (perf + cost guard).
MAX_GENERATED_CARDS = 60
DEFAULT_GENERATED_CARDS = 15


def validate_deck_name(raw: str | None, *, default: str = "Untitled deck") -> str:
    if raw is None or raw.strip() == "":
        return default
    name = " ".join(raw.split())
    if len(name) > DECK_NAME_MAX:
        raise FlashcardValidationError(f"Deck name must be at most {DECK_NAME_MAX} characters.")
    if any(ord(ch) < 32 for ch in name):
        raise FlashcardValidationError("Deck name contains invalid control characters.")
    return name


def validate_description(raw: str | None) -> str:
    if not raw:
        return ""
    desc = raw.strip()
    if len(desc) > DESCRIPTION_MAX:
        raise FlashcardValidationError(f"Description must be at most {DESCRIPTION_MAX} characters.")
    return desc


def validate_color(raw: str | None, *, default: str = "#6366f1") -> str:
    if not raw:
        return default
    color = raw.strip()
    if not _HEX_COLOR.match(color):
        raise FlashcardValidationError("Color must be a hex value like #6366f1.")
    return color


def validate_card_type(raw: str | None) -> str:
    t = (raw or "basic").strip().lower()
    if t not in CARD_TYPES:
        raise FlashcardValidationError(
            f"Unknown card type '{raw}'. Supported: {', '.join(CARD_TYPES)}."
        )
    return t


def validate_card_type_pref(raw: str | None) -> str:
    t = (raw or "mixed").strip().lower()
    if t not in CARD_TYPE_PREFS:
        raise FlashcardValidationError(
            f"Unknown card type preference '{raw}'. Supported: {', '.join(CARD_TYPE_PREFS)}."
        )
    return t


def validate_difficulty(raw: str | None) -> str:
    d = (raw or "medium").strip().lower()
    if d not in DIFFICULTIES:
        raise FlashcardValidationError(f"Unknown difficulty '{raw}'. Supported: {', '.join(DIFFICULTIES)}.")
    return d


def validate_scope(scope: str | None, *, document_id: str | None, document_ids: list | None) -> str:
    s = (scope or "").strip().lower()
    if not s:
        if document_ids:
            s = "multi"
        elif document_id:
            s = "document"
        else:
            s = "workspace"
    if s not in SCOPES or s == "manual":
        raise FlashcardValidationError(f"Unknown generation scope '{scope}'. Supported: document, multi, workspace.")
    if s == "document" and not document_id:
        raise FlashcardValidationError("A 'document' deck requires document_id.")
    if s == "multi" and not document_ids:
        raise FlashcardValidationError("A 'multi' deck requires document_ids.")
    return s


def validate_count(raw: int | None) -> int:
    n = raw if raw is not None else DEFAULT_GENERATED_CARDS
    if n < 1 or n > MAX_GENERATED_CARDS:
        raise FlashcardValidationError(f"Card count must be between 1 and {MAX_GENERATED_CARDS}.")
    return n


def validate_card_content(front: str | None, back: str | None, *, card_type: str) -> tuple[str, str]:
    front = (front or "").strip()
    back = (back or "").strip()
    if not front:
        raise FlashcardValidationError("A flashcard must have a front (question/prompt).")
    if len(front) > FRONT_MAX:
        raise FlashcardValidationError(f"Front must be at most {FRONT_MAX} characters.")
    if len(back) > BACK_MAX:
        raise FlashcardValidationError(f"Back must be at most {BACK_MAX} characters.")
    # Cloze cards may carry their answer in the text; others need a back.
    if card_type != "cloze" and not back:
        raise FlashcardValidationError("A flashcard must have a back (answer).")
    return front, back


def validate_hint(raw: str | None) -> str:
    if not raw:
        return ""
    hint = raw.strip()
    if len(hint) > HINT_MAX:
        raise FlashcardValidationError(f"Hint must be at most {HINT_MAX} characters.")
    return hint


def validate_rating(raw: str | None) -> str:
    from app.flashcards.scheduler import RATINGS  # local import: keep validation import-light

    r = (raw or "").strip().lower()
    if r not in RATINGS:
        raise FlashcardValidationError(f"Unknown rating '{raw}'. Supported: {', '.join(RATINGS)}.")
    return r


def default_deck_name(scope: str, *, subject: str | None = None, source: str | None = None) -> str:
    if subject:
        return f"{subject.strip()} — flashcards"[:DECK_NAME_MAX]
    label = {"document": "Document", "multi": "Documents", "workspace": "Workspace"}.get(scope, "Study")
    if source:
        return f"{source} flashcards"[:DECK_NAME_MAX]
    return f"{label} flashcards"
