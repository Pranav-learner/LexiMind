"""Flashcard data-access layer — the ONLY place that issues SQL for decks/cards/reviews.

Owner + workspace scoped, soft-delete aware. Batched citation reads (no N+1). Aggregation queries
(deck stats, review queue, learning analytics) live here so the service stays pure business logic.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.flashcards.models import Deck, Flashcard, FlashcardCitation, FlashcardReview
from app.flashcards.schemas import (
    ArchivedFilter,
    CardSortField,
    CardStatusFilter,
    DeckSortField,
    SortOrder,
)

# Cards at/above this mastery are considered "mastered" for analytics.
MASTERY_THRESHOLD = 0.8


def _now() -> datetime:
    # Naive UTC: SQLite reads DateTime columns back WITHOUT tzinfo, so all `now`-vs-stored
    # comparisons (review queue, deck stats, analytics) must use a naive-UTC clock to avoid
    # "can't compare offset-naive and offset-aware datetimes".
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FlashcardRepository:
    def __init__(self, db: Session):
        self.db = db

    # ================================================================ decks
    def get_deck(self, deck_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Deck]:
        stmt = select(Deck).where(Deck.id == deck_id, Deck.owner_id == owner_id)
        if not include_deleted:
            stmt = stmt.where(Deck.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_deck_by_id_only(self, deck_id: str) -> Optional[Deck]:
        return self.db.scalar(select(Deck).where(Deck.id == deck_id))

    def list_decks(
        self, owner_id: str, workspace_id: str, *, page: int = 1, page_size: int = 20,
        search: Optional[str] = None, archived: ArchivedFilter = ArchivedFilter.active,
        sort_by: DeckSortField = DeckSortField.updated_at, order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Deck], int]:
        conds = [Deck.owner_id == owner_id, Deck.workspace_id == workspace_id, Deck.deleted_at.is_(None)]
        if archived == ArchivedFilter.active:
            conds.append(Deck.is_archived.is_(False))
        elif archived == ArchivedFilter.archived:
            conds.append(Deck.is_archived.is_(True))
        if search:
            conds.append(func.lower(Deck.name).like(f"%{search.strip().lower()}%"))
        total = self.db.scalar(select(func.count()).select_from(Deck).where(*conds)) or 0
        column = getattr(Deck, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (select(Deck).where(*conds).order_by(direction(column), desc(Deck.id))
                .offset(max(0, page - 1) * page_size).limit(page_size))
        return list(self.db.scalars(stmt)), int(total)

    def create_deck(self, deck: Deck) -> Deck:
        self.db.add(deck)
        self.db.commit()
        self.db.refresh(deck)
        return deck

    def save_deck(self, deck: Deck) -> Deck:
        deck.updated_at = _now()
        self.db.commit()
        self.db.refresh(deck)
        return deck

    def recount_deck(self, deck_id: str) -> int:
        n = self.db.scalar(
            select(func.count()).select_from(Flashcard)
            .where(Flashcard.deck_id == deck_id, Flashcard.deleted_at.is_(None))
        ) or 0
        deck = self.db.get(Deck, deck_id)
        if deck is not None:
            deck.card_count = int(n)
            self.db.commit()
        return int(n)

    def soft_delete_deck(self, deck: Deck) -> None:
        deck.deleted_at = _now()
        # Soft-delete the deck's cards too so they leave every queue/stat.
        self.db.execute(
            Flashcard.__table__.update()
            .where(Flashcard.deck_id == deck.id, Flashcard.deleted_at.is_(None))
            .values(deleted_at=_now())
        )
        self.db.commit()

    def hard_delete_deck(self, deck: Deck) -> None:
        card_ids = list(self.db.scalars(select(Flashcard.id).where(Flashcard.deck_id == deck.id)))
        if card_ids:
            self.db.execute(delete(FlashcardCitation).where(FlashcardCitation.flashcard_id.in_(card_ids)))
            self.db.execute(delete(FlashcardReview).where(FlashcardReview.flashcard_id.in_(card_ids)))
            self.db.execute(delete(Flashcard).where(Flashcard.deck_id == deck.id))
        self.db.delete(deck)
        self.db.commit()

    # ================================================================ cards
    def get_card(self, card_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Flashcard]:
        stmt = select(Flashcard).where(Flashcard.id == card_id, Flashcard.owner_id == owner_id)
        if not include_deleted:
            stmt = stmt.where(Flashcard.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def list_cards(
        self, owner_id: str, workspace_id: str, *, deck_id: Optional[str] = None,
        page: int = 1, page_size: int = 20, search: Optional[str] = None,
        card_type: Optional[str] = None, status: CardStatusFilter = CardStatusFilter.any,
        favorite: Optional[bool] = None,
        sort_by: CardSortField = CardSortField.created_at, order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Flashcard], int]:
        conds = [Flashcard.owner_id == owner_id, Flashcard.workspace_id == workspace_id, Flashcard.deleted_at.is_(None)]
        if deck_id:
            conds.append(Flashcard.deck_id == deck_id)
        if card_type:
            conds.append(Flashcard.card_type == card_type)
        if favorite is not None:
            conds.append(Flashcard.is_favorite.is_(favorite))
        if status != CardStatusFilter.any:
            conds.append(Flashcard.status == status.value)
        if search:
            like = f"%{search.strip().lower()}%"
            conds.append(or_(func.lower(Flashcard.front).like(like), func.lower(Flashcard.back).like(like)))
        total = self.db.scalar(select(func.count()).select_from(Flashcard).where(*conds)) or 0
        column = getattr(Flashcard, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (select(Flashcard).where(*conds).order_by(direction(column), desc(Flashcard.id))
                .offset(max(0, page - 1) * page_size).limit(page_size))
        return list(self.db.scalars(stmt)), int(total)

    def create_card(self, card: Flashcard, citations: Optional[List[FlashcardCitation]] = None) -> Flashcard:
        self.db.add(card)
        self.db.flush()  # assign id
        if citations:
            for c in citations:
                c.flashcard_id = card.id
                c.workspace_id = card.workspace_id
            self.db.add_all(citations)
            card.citation_count = len(citations)
        self.db.commit()
        self.db.refresh(card)
        return card

    def bulk_add_cards(self, cards_with_cits: List[Tuple[Flashcard, List[FlashcardCitation]]]) -> int:
        """Insert many generated cards + their citations in one commit (bulk generation perf)."""
        for card, cits in cards_with_cits:
            self.db.add(card)
            self.db.flush()
            for c in cits:
                c.flashcard_id = card.id
                c.workspace_id = card.workspace_id
            if cits:
                self.db.add_all(cits)
                card.citation_count = len(cits)
        self.db.commit()
        return len(cards_with_cits)

    def save_card(self, card: Flashcard) -> Flashcard:
        card.updated_at = _now()
        self.db.commit()
        self.db.refresh(card)
        return card

    def soft_delete_card(self, card: Flashcard) -> None:
        card.deleted_at = _now()
        self.db.commit()

    def citations_for(self, card_ids: List[str]) -> Dict[str, List[FlashcardCitation]]:
        if not card_ids:
            return {}
        grouped: Dict[str, List[FlashcardCitation]] = defaultdict(list)
        for c in self.db.scalars(select(FlashcardCitation).where(FlashcardCitation.flashcard_id.in_(card_ids))):
            grouped[c.flashcard_id].append(c)
        return grouped

    def clear_ai_cards(self, deck_id: str) -> None:
        """Remove AI-generated cards (+ their citations) before a regenerate; keep manual cards."""
        ids = list(self.db.scalars(
            select(Flashcard.id).where(Flashcard.deck_id == deck_id, Flashcard.created_by == "ai")
        ))
        if ids:
            self.db.execute(delete(FlashcardCitation).where(FlashcardCitation.flashcard_id.in_(ids)))
            self.db.execute(delete(FlashcardReview).where(FlashcardReview.flashcard_id.in_(ids)))
            self.db.execute(delete(Flashcard).where(Flashcard.id.in_(ids)))
            self.db.commit()

    # ================================================================ review queue
    def review_queue(
        self, owner_id: str, workspace_id: str, *, deck_id: Optional[str] = None,
        now: Optional[datetime] = None, limit: int = 50, new_limit: int = 20,
    ) -> Tuple[List[Flashcard], int, int, int]:
        """Return (cards, total_due, new_count, due_count).

        Due cards (interval elapsed) come first ordered by next_review_at; then up to `new_limit`
        never-seen cards. `total_due` counts due+new available (not just the served slice).
        """
        now = now or _now()
        base = [Flashcard.owner_id == owner_id, Flashcard.workspace_id == workspace_id,
                Flashcard.deleted_at.is_(None), Flashcard.status == "active"]
        if deck_id:
            base.append(Flashcard.deck_id == deck_id)

        due_conds = [*base, Flashcard.next_review_at.is_not(None), Flashcard.next_review_at <= now]
        new_conds = [*base, Flashcard.next_review_at.is_(None)]

        due_count = self.db.scalar(select(func.count()).select_from(Flashcard).where(*due_conds)) or 0
        new_count = self.db.scalar(select(func.count()).select_from(Flashcard).where(*new_conds)) or 0

        due_cards = list(self.db.scalars(
            select(Flashcard).where(*due_conds).order_by(asc(Flashcard.next_review_at)).limit(limit)
        ))
        remaining = max(0, limit - len(due_cards))
        new_cards: List[Flashcard] = []
        if remaining:
            new_cards = list(self.db.scalars(
                select(Flashcard).where(*new_conds).order_by(asc(Flashcard.created_at)).limit(min(remaining, new_limit))
            ))
        cards = due_cards + new_cards
        return cards, int(due_count) + int(new_count), int(new_count), int(due_count)

    def add_review(self, review: FlashcardReview) -> FlashcardReview:
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    # ================================================================ deck stats
    def deck_stats(self, deck_id: str, *, now: Optional[datetime] = None) -> Dict[str, float]:
        now = now or _now()
        rows = list(self.db.scalars(
            select(Flashcard).where(Flashcard.deck_id == deck_id, Flashcard.deleted_at.is_(None))
        ))
        stats = {"total": 0, "new": 0, "due": 0, "learning": 0, "review": 0,
                 "suspended": 0, "mastered": 0, "avg_mastery": 0.0}
        mastery_sum = 0.0
        for c in rows:
            stats["total"] += 1
            if c.status == "suspended":
                stats["suspended"] += 1
                continue
            if c.mastery_score >= MASTERY_THRESHOLD:
                stats["mastered"] += 1
            mastery_sum += c.mastery_score
            if c.next_review_at is None:
                stats["new"] += 1
            elif c.next_review_at <= now:
                stats["due"] += 1
            if c.learning_stage in ("learning", "relearning", "new"):
                stats["learning"] += 1
            elif c.learning_stage == "review":
                stats["review"] += 1
        active = stats["total"] - stats["suspended"]
        stats["avg_mastery"] = round(mastery_sum / active, 4) if active else 0.0
        return stats

    def stats_for_decks(self, deck_ids: List[str], *, now: Optional[datetime] = None) -> Dict[str, Dict]:
        return {d: self.deck_stats(d, now=now) for d in deck_ids}

    # ================================================================ analytics
    def analytics(self, owner_id: str, workspace_id: str, *, now: Optional[datetime] = None,
                  days: int = 30) -> Dict:
        now = now or _now()
        today = now.date()
        cards = list(self.db.scalars(
            select(Flashcard).where(Flashcard.owner_id == owner_id,
                                    Flashcard.workspace_id == workspace_id,
                                    Flashcard.deleted_at.is_(None))
        ))
        total = len(cards)
        active = [c for c in cards if c.status == "active"]
        new_cards = sum(1 for c in active if c.next_review_at is None)
        due_today = sum(1 for c in active if c.next_review_at is not None and c.next_review_at <= now)
        mastered = sum(1 for c in cards if c.mastery_score >= MASTERY_THRESHOLD and c.status != "suspended")
        suspended = sum(1 for c in cards if c.status == "suspended")
        avg_mastery = round(sum(c.mastery_score for c in active) / len(active), 4) if active else 0.0

        # Review aggregates.
        reviews = list(self.db.scalars(
            select(FlashcardReview).where(FlashcardReview.owner_id == owner_id,
                                          FlashcardReview.workspace_id == workspace_id)
        ))
        reviews_total = len(reviews)
        correct_total = sum(1 for r in reviews if r.was_correct)
        reviews_today = sum(1 for r in reviews if r.review_date.date() == today)
        avg_rt = int(sum(r.response_time_ms for r in reviews) / reviews_total) if reviews_total else 0
        accuracy = round(correct_total / reviews_total, 4) if reviews_total else 0.0
        # Retention = accuracy on cards already in the review stage (true long-term recall).
        review_stage_ids = {c.id for c in cards if c.learning_stage == "review"}
        rs_reviews = [r for r in reviews if r.flashcard_id in review_stage_ids]
        retention = round(sum(1 for r in rs_reviews if r.was_correct) / len(rs_reviews), 4) if rs_reviews else 0.0

        # Daily activity (last `days`) + study streak.
        by_day: Dict[str, Dict[str, int]] = {}
        review_days = set()
        for r in reviews:
            d = r.review_date.date()
            key = d.isoformat()
            bucket = by_day.setdefault(key, {"reviews": 0, "correct": 0})
            bucket["reviews"] += 1
            bucket["correct"] += 1 if r.was_correct else 0
            review_days.add(d)

        from datetime import timedelta
        daily = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            key = d.isoformat()
            b = by_day.get(key, {"reviews": 0, "correct": 0})
            daily.append({"date": key, "reviews": b["reviews"], "correct": b["correct"]})

        # Streak: consecutive days ending today (or yesterday) with ≥1 review.
        streak = 0
        cursor = today
        if today not in review_days and (today - timedelta(days=1)) in review_days:
            cursor = today - timedelta(days=1)
        while cursor in review_days:
            streak += 1
            cursor = cursor - timedelta(days=1)

        deck_count = self.db.scalar(
            select(func.count()).select_from(Deck)
            .where(Deck.owner_id == owner_id, Deck.workspace_id == workspace_id, Deck.deleted_at.is_(None))
        ) or 0

        return {
            "total_cards": total, "active_cards": len(active), "new_cards": new_cards,
            "due_today": due_today, "mastered_cards": mastered, "suspended_cards": suspended,
            "reviews_today": reviews_today, "reviews_total": reviews_total, "accuracy": accuracy,
            "retention": retention, "avg_response_time_ms": avg_rt, "study_streak_days": streak,
            "avg_mastery": avg_mastery, "daily_activity": daily, "deck_count": int(deck_count),
        }
