"""The recommendation engine — data-driven knowledge insights (deterministic, not hard-coded).

`generate_insights` turns the already-computed dashboard sections into a ranked list of actionable
recommendations ("You haven't reviewed X in 12 days", "75% of your flashcards are mastered"). It is
a pure function over section payloads plus a couple of cheap direct queries (stale-deck detection),
so it adds no expensive work and is fully testable. New rules are added by appending to `_RULES`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List

from app.analytics.aggregators import AggContext


def _mk(id_, kind, severity, icon, title, message, *, action_label=None, action_route=None) -> dict:
    return {"id": id_, "kind": kind, "severity": severity, "icon": icon, "title": title,
            "message": message, "action_label": action_label, "action_route": action_route}


# Ordering: warnings first (need attention), then actionable info, then positive reinforcement.
_SEVERITY_ORDER = {"warning": 0, "info": 1, "positive": 2}


def generate_insights(ctx: AggContext, knowledge: dict, ai_usage: dict, learning: dict, documents: dict) -> List[dict]:
    ws = ctx.workspace_id
    out: List[dict] = []
    docs = documents.get("items", [])
    total_cards = ai_usage.get("flashcards_generated", 0)

    # --- streak ---
    streak = learning.get("study_streak_days", 0)
    if streak >= 3:
        out.append(_mk("streak", "streak", "positive", "🔥", f"{streak}-day study streak",
                       f"You've studied {streak} days in a row — keep the momentum going!"))
    elif learning.get("cards_reviewed", 0) > 0 and streak == 0:
        out.append(_mk("streak_reset", "streak", "warning", "⏰", "Your study streak reset",
                       "Review a few cards today to start a new streak.",
                       action_label="Review now", action_route=f"/workspace/{ws}/flashcards/review"))

    # --- due reviews ---
    due = learning.get("due_today", 0) + learning.get("new_cards", 0)
    if due > 0:
        out.append(_mk("due", "review", "info", "🎯", f"{due} card{'s' if due != 1 else ''} to review",
                       "Spaced repetition works best when you review on schedule.",
                       action_label="Study now", action_route=f"/workspace/{ws}/flashcards/review"))

    # --- mastery ---
    if total_cards > 0:
        pct = round(learning.get("mastered_cards", 0) / total_cards * 100)
        out.append(_mk("mastery", "milestone", "positive" if pct >= 50 else "info", "🏆",
                       f"{pct}% of your flashcards are mastered",
                       f"{learning.get('mastered_cards', 0)} of {total_cards} cards are well-spaced and reliably recalled."))

    # --- retention warning ---
    if learning.get("cards_reviewed", 0) >= 10 and learning.get("retention", 1.0) < 0.6:
        out.append(_mk("retention", "warning", "warning", "🧠",
                       f"Retention is {round(learning['retention'] * 100)}%",
                       "Consider shorter intervals or reviewing more often to improve recall.",
                       action_label="Review", action_route=f"/workspace/{ws}/flashcards/review"))

    # --- stale deck ---
    stale = _stalest_deck(ctx)
    if stale:
        name, days = stale
        out.append(_mk("stale_deck", "review", "warning", "📆",
                       f"Haven't reviewed “{name}” in {days} days",
                       "This deck is overdue — a quick review will refresh it.",
                       action_label="Study deck", action_route=f"/workspace/{ws}/flashcards"))

    # --- coverage: documents without a summary ---
    no_summary = [d for d in docs if d.get("summaries", 0) == 0]
    if no_summary:
        n = len(no_summary)
        out.append(_mk("coverage_summary", "coverage", "info", "📄",
                       f"{n} document{'s' if n != 1 else ''} have no summary yet",
                       "Generate summaries to make them easier to review and cite.",
                       action_label="Summaries", action_route=f"/workspace/{ws}/summaries"))

    # --- most-referenced document ---
    cited = max(docs, key=lambda d: d.get("citation_count", 0), default=None)
    if cited and cited.get("citation_count", 0) > 0:
        out.append(_mk("top_source", "tip", "positive", "🔗",
                       f"“{cited['display_name']}” is your most-referenced source",
                       f"It has produced {cited['citation_count']} citations across your knowledge base."))

    # --- highest question frequency ---
    asked = max(docs, key=lambda d: d.get("question_frequency", 0), default=None)
    if asked and asked.get("question_frequency", 0) > 0 and (not cited or asked["id"] != cited["id"]):
        out.append(_mk("top_asked", "tip", "info", "❓",
                       f"“{asked['display_name']}” has the highest question frequency",
                       "You reference it often in chat — consider generating flashcards from it.",
                       action_label="Flashcards", action_route=f"/workspace/{ws}/flashcards"))

    # --- upload milestone ---
    ndocs = knowledge.get("documents", 0)
    if ndocs >= 5:
        out.append(_mk("milestone_docs", "milestone", "positive", "📚",
                       f"You've built a library of {ndocs} documents",
                       f"That's {knowledge.get('pages', 0)} pages and {knowledge.get('chunks', 0)} indexed chunks of knowledge."))

    out.sort(key=lambda i: _SEVERITY_ORDER.get(i["severity"], 3))
    return out[:8]


def _stalest_deck(ctx: AggContext):
    """Return (deck_name, days_since_last_review) for the most-overdue non-empty deck (>7 days)."""
    from sqlalchemy import func, select
    from app.flashcards.models import Deck, Flashcard, FlashcardReview

    rows = ctx.db.execute(
        select(Deck.name, func.max(FlashcardReview.review_date))
        .join(FlashcardReview, FlashcardReview.deck_id == Deck.id)
        .where(Deck.workspace_id == ctx.workspace_id, Deck.deleted_at.is_(None))
        .group_by(Deck.id)
    ).all()
    worst = None
    for name, last in rows:
        if last is None:
            continue
        days = (ctx.now - last).days if isinstance(last, datetime) else 0
        if days > 7 and (worst is None or days > worst[1]):
            # Only if the deck actually has active cards.
            has_cards = ctx.db.scalar(
                select(func.count()).select_from(Flashcard)
                .join(Deck, Deck.id == Flashcard.deck_id)
                .where(Deck.name == name, Deck.workspace_id == ctx.workspace_id,
                       Flashcard.deleted_at.is_(None), Flashcard.status == "active")
            ) or 0
            if has_cards:
                worst = (name, days)
    return worst


_RULES: List[Callable] = []  # reserved: future modules can register additional insight rules
