"""Spaced-Repetition scheduler — an SM-2 variant (the science behind active recall).

This is the ONLY place scheduling math lives. It is a PURE function of (current SRS state, rating)
→ (new SRS state); it touches no DB and no clock beyond an injected `now`, so it is exhaustively
unit-testable and deterministic.

WHY SM-2 (SuperMemo-2): it is the proven, well-understood algorithm behind Anki and most SRS
tools. Each card carries an *ease factor* (how "easy" it is for the user) and an *interval* (days
until the next review). A successful review multiplies the interval by the ease factor, so
well-known cards are shown exponentially less often — the spacing effect that maximizes long-term
retention for minimal review time. We add Anki-style four-button grading (Again/Hard/Good/Easy)
and learning/relearning steps on top of textbook SM-2 for a smoother early experience — an
"improved variant" rather than raw SM-2.

Rating → SM-2 quality mapping (q ∈ 0..5; q < 3 is a lapse):
    again → 2   hard → 3   good → 4   easy → 5

State machine (`learning_stage`):
    new ──good/easy──► review ──again──► relearning ──good──► review
        └──again/hard──► learning ──good──► review

Intervals are whole days (day-granularity SRS — no intraday steps — which keeps the model simple,
timezone-robust, and matches a "review once a day" study habit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---- tunables (kept here so the algorithm is self-documenting) ------------------------------
MIN_EASE = 1.3
DEFAULT_EASE = 2.5
EASY_BONUS = 1.3           # extra interval multiplier when the user rates a review card "easy"
HARD_INTERVAL_FACTOR = 1.2  # a "hard" success grows the interval only modestly
LAPSE_INTERVAL = 1          # after forgetting, re-show tomorrow
FIRST_INTERVAL = 1          # first successful graduation → 1 day
SECOND_INTERVAL = 6         # classic SM-2 second interval → 6 days
EASY_FIRST_INTERVAL = 4     # a brand-new card rated "easy" skips ahead
NEW_LAPSE_EASE_PENALTY = 0.20
HARD_EASE_PENALTY = 0.15
EASY_EASE_BONUS = 0.15
MASTERY_INTERVAL_CAP = 60   # an interval of this many days counts as "fully spaced"

RATINGS = ("again", "hard", "good", "easy")
_QUALITY = {"again": 2, "hard": 3, "good": 4, "easy": 5}


@dataclass
class SRSState:
    """The subset of a Flashcard's columns the scheduler reads and writes."""

    ease_factor: float = DEFAULT_EASE
    interval_days: int = 0
    repetitions: int = 0
    review_count: int = 0
    lapse_count: int = 0
    correct_count: int = 0
    learning_stage: str = "new"          # new | learning | review | relearning
    mastery_score: float = 0.0
    next_review_at: datetime | None = None
    last_reviewed_at: datetime | None = None


@dataclass
class ScheduleResult:
    state: SRSState
    quality: int
    was_correct: bool
    prev_interval: int
    scheduled_interval: int


def _clamp_ease(ef: float) -> float:
    return max(MIN_EASE, round(ef, 4))


def _sm2_ease(ef: float, quality: int) -> float:
    """Textbook SM-2 ease update: EF' = EF + (0.1 - (5-q)(0.08 + (5-q)0.02))."""
    return _clamp_ease(ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))


def _mastery(state: SRSState) -> float:
    """A 0..1 learning-strength estimate blending interval maturity, ease, and accuracy.

    - interval maturity: how close the current interval is to "fully spaced" (cap).
    - ease term: normalized ease factor (1.3..~3.0).
    - accuracy: correct / reviews.
    Weighted so a card only approaches 1.0 once it is both well-spaced AND reliably recalled.
    """
    if state.review_count == 0:
        return 0.0
    interval_term = min(1.0, state.interval_days / MASTERY_INTERVAL_CAP)
    ease_term = max(0.0, min(1.0, (state.ease_factor - MIN_EASE) / (DEFAULT_EASE + 0.5 - MIN_EASE)))
    accuracy = state.correct_count / state.review_count
    score = 0.5 * interval_term + 0.2 * ease_term + 0.3 * accuracy
    return round(max(0.0, min(1.0, score)), 4)


def schedule(state: SRSState, rating: str, *, now: datetime | None = None) -> ScheduleResult:
    """Apply one review to `state` and return the new state + review snapshot.

    `rating` ∈ {again, hard, good, easy}. `now` is injectable for deterministic tests.
    """
    if rating not in _QUALITY:
        raise ValueError(f"Unknown rating '{rating}'. Expected one of {RATINGS}.")
    now = now or datetime.now(timezone.utc)
    quality = _QUALITY[rating]
    prev_interval = state.interval_days
    was_correct = quality >= 3

    ns = SRSState(
        ease_factor=state.ease_factor,
        interval_days=state.interval_days,
        repetitions=state.repetitions,
        review_count=state.review_count + 1,
        lapse_count=state.lapse_count,
        correct_count=state.correct_count + (1 if was_correct else 0),
        learning_stage=state.learning_stage,
        last_reviewed_at=now,
    )

    if rating == "again":
        # Lapse: reset the success streak, drop ease, re-show tomorrow, enter relearning.
        ns.lapse_count = state.lapse_count + 1
        ns.repetitions = 0
        ns.ease_factor = _clamp_ease(state.ease_factor - NEW_LAPSE_EASE_PENALTY)
        ns.interval_days = LAPSE_INTERVAL
        ns.learning_stage = "relearning" if state.learning_stage in ("review", "relearning") else "learning"
    else:
        # A successful recall. Update ease per SM-2, then grow the interval by stage.
        ns.ease_factor = _sm2_ease(state.ease_factor, quality)
        if rating == "hard":
            ns.ease_factor = _clamp_ease(ns.ease_factor - HARD_EASE_PENALTY)
        elif rating == "easy":
            ns.ease_factor = _clamp_ease(ns.ease_factor + EASY_EASE_BONUS)

        if state.learning_stage in ("new", "learning", "relearning"):
            # Graduating from a learning phase.
            if rating == "easy":
                ns.interval_days = EASY_FIRST_INTERVAL
            elif rating == "hard":
                ns.interval_days = FIRST_INTERVAL
            else:  # good
                ns.interval_days = FIRST_INTERVAL if state.repetitions == 0 else SECOND_INTERVAL
            ns.repetitions = state.repetitions + 1
            ns.learning_stage = "review"
        else:
            # Already a review card → exponential spacing.
            base = max(1, state.interval_days)
            if rating == "hard":
                grown = round(base * HARD_INTERVAL_FACTOR)
            elif rating == "easy":
                grown = round(base * ns.ease_factor * EASY_BONUS)
            else:  # good
                grown = round(base * ns.ease_factor)
            ns.interval_days = max(state.interval_days + 1, grown)  # always move forward
            ns.repetitions = state.repetitions + 1
            ns.learning_stage = "review"

    ns.mastery_score = _mastery(ns)
    ns.next_review_at = now + timedelta(days=ns.interval_days)
    return ScheduleResult(
        state=ns, quality=quality, was_correct=was_correct,
        prev_interval=prev_interval, scheduled_interval=ns.interval_days,
    )


def preview_intervals(state: SRSState, *, now: datetime | None = None) -> dict:
    """Return the interval (days) each button would schedule — for the review UI's button labels."""
    return {r: schedule(state, r, now=now).scheduled_interval for r in RATINGS}
