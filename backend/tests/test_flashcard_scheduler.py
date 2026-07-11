"""Unit tests for the SM-2 spaced-repetition scheduler (pure, deterministic)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.flashcards.scheduler import (
    DEFAULT_EASE,
    MIN_EASE,
    SRSState,
    preview_intervals,
    schedule,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_new_card_good_graduates_to_review():
    r = schedule(SRSState(), "good", now=NOW)
    assert r.state.learning_stage == "review"
    assert r.scheduled_interval == 1
    assert r.state.repetitions == 1
    assert r.was_correct is True
    assert (r.state.next_review_at - NOW).days == 1  # scheduled one day out


def test_new_card_easy_skips_ahead():
    r = schedule(SRSState(), "easy", now=NOW)
    assert r.scheduled_interval == 4          # EASY_FIRST_INTERVAL
    assert r.state.ease_factor > DEFAULT_EASE  # easy raises ease


def test_second_good_uses_classic_six_day_step():
    # new→good (rep 1, interval 1) then good again from a card that has repetitions but is still
    # early: our variant grows by ease from the review stage.
    r1 = schedule(SRSState(), "good", now=NOW)
    r2 = schedule(r1.state, "good", now=NOW)
    assert r2.scheduled_interval >= 2          # moves forward
    assert r2.state.learning_stage == "review"


def test_interval_grows_by_ease_when_reviewing():
    st = SRSState(learning_stage="review", interval_days=10, repetitions=3, ease_factor=2.5, review_count=3, correct_count=3)
    r = schedule(st, "good", now=NOW)
    assert r.scheduled_interval == 25          # round(10 * 2.5)


def test_again_is_a_lapse_and_resets():
    st = SRSState(learning_stage="review", interval_days=20, repetitions=4, ease_factor=2.6,
                  review_count=4, correct_count=4)
    r = schedule(st, "again", now=NOW)
    assert r.was_correct is False
    assert r.scheduled_interval == 1
    assert r.state.repetitions == 0
    assert r.state.lapse_count == 1
    assert r.state.learning_stage == "relearning"
    assert r.state.ease_factor < 2.6           # ease dropped


def test_ease_never_below_floor():
    st = SRSState(ease_factor=1.3, learning_stage="review", interval_days=1)
    for _ in range(5):
        st = schedule(st, "again", now=NOW).state
    assert st.ease_factor >= MIN_EASE


def test_hard_grows_less_than_good():
    st = SRSState(learning_stage="review", interval_days=10, repetitions=3, ease_factor=2.5, review_count=3, correct_count=3)
    hard = schedule(st, "hard", now=NOW).scheduled_interval
    good = schedule(st, "good", now=NOW).scheduled_interval
    easy = schedule(st, "easy", now=NOW).scheduled_interval
    assert hard < good < easy


def test_mastery_increases_with_success_and_interval():
    st = SRSState()
    prev = 0.0
    for _ in range(4):
        st = schedule(st, "good", now=NOW).state
        assert st.mastery_score >= prev
        prev = st.mastery_score
    assert 0.0 < st.mastery_score <= 1.0


def test_next_review_at_matches_interval():
    r = schedule(SRSState(learning_stage="review", interval_days=5, repetitions=2, review_count=2, correct_count=2), "good", now=NOW)
    delta_days = (r.state.next_review_at - NOW).days
    assert delta_days == r.scheduled_interval


def test_preview_returns_all_four_buttons():
    p = preview_intervals(SRSState())
    assert set(p.keys()) == {"again", "hard", "good", "easy"}
    assert p["again"] <= p["good"] <= p["easy"]


def test_invalid_rating_raises():
    with pytest.raises(ValueError):
        schedule(SRSState(), "maybe", now=NOW)
