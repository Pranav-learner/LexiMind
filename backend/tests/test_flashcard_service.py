"""Unit tests for FlashcardService: decks, cards, generation, review (SRS), analytics."""

from __future__ import annotations

import pytest

from app.flashcards.errors import FlashcardStateError
from app.flashcards.repository import FlashcardRepository
from app.flashcards.service import FlashcardService
from tests.conftest import FakeFlashcardEngine


def _svc(db):
    return FlashcardService(FlashcardRepository(db))


def test_create_deck_and_default_deck(db_session):
    svc = _svc(db_session)
    d = svc.create_deck("u1", "w1", name="Bio")
    assert d.name == "Bio" and d.status == "ready" and d.scope == "manual"
    default1 = svc.get_default_deck("u1", "w1")
    default2 = svc.get_default_deck("u1", "w1")
    assert default1.id == default2.id and default1.name == "My Flashcards"


def test_create_card_uses_default_deck_and_citations(db_session):
    svc = _svc(db_session)
    card = svc.create_card("u1", "w1", deck_id=None, front="What is RAM?", back="Volatile memory.",
                           citations=[{"document_id": "doc_x", "page_number": 4, "citation_text": "ram"}])
    assert card.deck_id  # attached to the auto-created default deck
    assert card.citation_count == 1
    assert card.learning_stage == "new" and card.next_review_at is None


def test_generate_now_bulk_persists_cards(db_session):
    svc = _svc(db_session)
    deck = svc.generate_deck("u1", "w1", scope="workspace", count=12)
    assert deck.status == "queued" and deck.target_count == 12
    done = svc.generate_now(deck.id, FakeFlashcardEngine(), count=12)
    assert done.status == "completed" and done.progress == 100
    assert done.card_count == 12
    cards, total = svc.list_cards("u1", "w1", deck_id=deck.id)
    assert total == 12
    # Each generated card carries a citation.
    _, cits = svc.get_card_detail(cards[0].id, "u1")
    assert len(cits) == 1


def test_review_queue_orders_due_then_new(db_session):
    svc = _svc(db_session)
    deck = svc.generate_deck("u1", "w1", scope="workspace", count=5)
    svc.generate_now(deck.id, FakeFlashcardEngine(), count=5)
    cards, _cit, total_due, new_count, due_count = svc.review_queue("u1", "w1")
    assert new_count == 5 and due_count == 0 and total_due == 5
    assert all(c.next_review_at is None for c in cards)  # all new


def test_submit_review_schedules_and_logs(db_session):
    svc = _svc(db_session)
    card = svc.create_card("u1", "w1", deck_id=None, front="Q?", back="A")
    updated = svc.submit_review(card.id, "u1", rating="good", response_time_ms=1500)
    assert updated.review_count == 1 and updated.correct_count == 1
    assert updated.next_review_at is not None and updated.interval_days == 1
    assert updated.learning_stage == "review"
    # A review row was logged (drives analytics).
    an = svc.analytics("u1", "w1")
    assert an["reviews_total"] == 1 and an["reviews_today"] == 1 and an["accuracy"] == 1.0


def test_again_review_increments_lapse(db_session):
    svc = _svc(db_session)
    card = svc.create_card("u1", "w1", deck_id=None, front="Q?", back="A")
    svc.submit_review(card.id, "u1", rating="good")
    lapsed = svc.submit_review(card.id, "u1", rating="again")
    assert lapsed.lapse_count == 1 and lapsed.learning_stage == "relearning"


def test_suspend_blocks_review(db_session):
    svc = _svc(db_session)
    card = svc.create_card("u1", "w1", deck_id=None, front="Q?", back="A")
    svc.suspend_card(card.id, "u1", suspended=True)
    with pytest.raises(FlashcardStateError):
        svc.submit_review(card.id, "u1", rating="good")


def test_reset_card_returns_to_new(db_session):
    svc = _svc(db_session)
    card = svc.create_card("u1", "w1", deck_id=None, front="Q?", back="A")
    svc.submit_review(card.id, "u1", rating="good")
    reset = svc.reset_card(card.id, "u1")
    assert reset.learning_stage == "new" and reset.next_review_at is None and reset.review_count == 0


def test_regenerate_requires_ai_or_scoped_deck(db_session):
    svc = _svc(db_session)
    manual = svc.create_deck("u1", "w1", name="Manual")
    with pytest.raises(FlashcardStateError):
        svc.reset_for_regenerate(manual.id, "u1")


def test_deck_stats_and_mastery_counts(db_session):
    svc = _svc(db_session)
    deck = svc.generate_deck("u1", "w1", scope="workspace", count=3)
    svc.generate_now(deck.id, FakeFlashcardEngine(), count=3)
    stats = svc.deck_stats(deck.id, "u1")
    assert stats["total"] == 3 and stats["new"] == 3 and stats["mastered"] == 0


def test_analytics_streak_and_accuracy(db_session):
    svc = _svc(db_session)
    c1 = svc.create_card("u1", "w1", deck_id=None, front="Q1", back="A1")
    c2 = svc.create_card("u1", "w1", deck_id=None, front="Q2", back="A2")
    svc.submit_review(c1.id, "u1", rating="good")
    svc.submit_review(c2.id, "u1", rating="again")
    an = svc.analytics("u1", "w1")
    assert an["reviews_total"] == 2 and an["accuracy"] == 0.5
    assert an["study_streak_days"] == 1
    assert len(an["daily_activity"]) == 30
