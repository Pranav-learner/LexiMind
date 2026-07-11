"""Unit tests for pure flashcard/deck validation."""

from __future__ import annotations

import pytest

from app.flashcards import validation as v
from app.flashcards.errors import FlashcardValidationError


def test_deck_name_defaults_and_normalizes():
    assert v.validate_deck_name(None) == "Untitled deck"
    assert v.validate_deck_name("  a   b ") == "a b"
    with pytest.raises(FlashcardValidationError):
        v.validate_deck_name("x" * 201)


def test_card_type_and_pref():
    assert v.validate_card_type("CLOZE") == "cloze"
    with pytest.raises(FlashcardValidationError):
        v.validate_card_type("multiple_choice")   # reserved but not yet valid
    assert v.validate_card_type_pref(None) == "mixed"
    with pytest.raises(FlashcardValidationError):
        v.validate_card_type_pref("essay")


def test_scope_inference_and_rules():
    assert v.validate_scope(None, document_id=None, document_ids=None) == "workspace"
    assert v.validate_scope(None, document_id="d", document_ids=None) == "document"
    assert v.validate_scope(None, document_id=None, document_ids=["a"]) == "multi"
    with pytest.raises(FlashcardValidationError):
        v.validate_scope("manual", document_id=None, document_ids=None)   # not a generation scope
    with pytest.raises(FlashcardValidationError):
        v.validate_scope("document", document_id=None, document_ids=None)


def test_count_bounds():
    assert v.validate_count(None) == v.DEFAULT_GENERATED_CARDS
    assert v.validate_count(10) == 10
    with pytest.raises(FlashcardValidationError):
        v.validate_count(0)
    with pytest.raises(FlashcardValidationError):
        v.validate_count(v.MAX_GENERATED_CARDS + 1)


def test_card_content_rules():
    front, back = v.validate_card_content("Q?", "A", card_type="basic")
    assert front == "Q?" and back == "A"
    with pytest.raises(FlashcardValidationError):
        v.validate_card_content("", "A", card_type="basic")       # front required
    with pytest.raises(FlashcardValidationError):
        v.validate_card_content("Q?", "", card_type="basic")      # non-cloze needs a back
    # Cloze may omit the back (answer embedded in the text).
    f, b = v.validate_card_content("The CPU uses ____ scheduling.", "", card_type="cloze")
    assert f.startswith("The CPU")


def test_rating_validation():
    assert v.validate_rating("Good") == "good"
    with pytest.raises(FlashcardValidationError):
        v.validate_rating("meh")


def test_color_and_difficulty():
    assert v.validate_color(None) == "#6366f1"
    with pytest.raises(FlashcardValidationError):
        v.validate_color("red")
    assert v.validate_difficulty(None) == "medium"
    with pytest.raises(FlashcardValidationError):
        v.validate_difficulty("impossible")
