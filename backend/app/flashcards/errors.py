"""Flashcard domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class FlashcardError(Exception):
    status_code = 400
    code = "flashcard_error"


class DeckNotFound(FlashcardError):
    status_code = 404
    code = "deck_not_found"

    def __init__(self, deck_id: str):
        super().__init__(f"Deck '{deck_id}' was not found.")


class CardNotFound(FlashcardError):
    status_code = 404
    code = "card_not_found"

    def __init__(self, card_id: str):
        super().__init__(f"Flashcard '{card_id}' was not found.")


class SourceNotFound(FlashcardError):
    """A generation/conversion source (note/summary/message) could not be resolved."""

    status_code = 404
    code = "source_not_found"


class FlashcardValidationError(FlashcardError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)


class FlashcardStateError(FlashcardError):
    """Illegal state transition (e.g. cancelling a ready deck, reviewing a suspended card)."""

    status_code = 409
    code = "invalid_state"
