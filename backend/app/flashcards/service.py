"""Flashcard business logic — decks, cards, AI generation, SRS review, and analytics.

Every generation path (document / note / summary / chat / selection) funnels through one service and
the same models. AI generation is asynchronous like notes/summaries: `generate_deck` enqueues a
`queued` deck; a background runner later calls `generate_now`, which consumes the injected engine's
events, persists cards + citations in bulk, tracks progress, and honors cancellation. Reviews are
scheduled by the pure `scheduler` (SM-2) — this service only persists its outputs and the review log.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.flashcards import validation
from app.flashcards.errors import (
    CardNotFound,
    DeckNotFound,
    FlashcardStateError,
    SourceNotFound,
)
from app.flashcards.models import Deck, Flashcard, FlashcardCitation, FlashcardReview
from app.flashcards.repository import FlashcardRepository
from app.flashcards.scheduler import SRSState, preview_intervals, schedule
from app.flashcards.schemas import (
    ArchivedFilter,
    CardSortField,
    CardStatusFilter,
    DeckSortField,
    SortOrder,
)


def _now() -> datetime:
    # Naive UTC to match SQLite's tz-stripped reads (see repository._now). The SRS scheduler,
    # review timestamps, and next_review_at all flow from here so comparisons stay consistent.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FlashcardService:
    def __init__(self, repo: FlashcardRepository, workspace_service=None):
        self.repo = repo
        self.workspace_service = workspace_service

    # ------------------------------------------------------------------ helpers
    def _deck_or_404(self, deck_id: str, owner_id: str) -> Deck:
        d = self.repo.get_deck(deck_id, owner_id)
        if d is None:
            raise DeckNotFound(deck_id)
        return d

    def _card_or_404(self, card_id: str, owner_id: str) -> Flashcard:
        c = self.repo.get_card(card_id, owner_id)
        if c is None:
            raise CardNotFound(card_id)
        return c

    def _bump_ws(self, workspace_id: str, owner_id: str, delta: int) -> None:
        if self.workspace_service is None or delta == 0:
            return
        try:
            self.workspace_service.adjust_counter(workspace_id, owner_id, "flashcard_count", delta)
        except Exception:
            pass

    def _citation_rows(self, cits: List[Dict[str, Any]], workspace_id: str) -> List[FlashcardCitation]:
        return [
            FlashcardCitation(
                document_id=c.get("document_id"), chunk_id=c.get("chunk_id"),
                page_number=c.get("page_number"), workspace_id=workspace_id,
                citation_text=(c.get("text") or c.get("citation_text") or c.get("source") or "")[:2000],
                confidence=c.get("confidence"),
            ) for c in cits
        ]

    # ================================================================ decks
    def create_deck(self, owner_id: str, workspace_id: str, *, name: Optional[str] = None,
                    description: Optional[str] = None, color: Optional[str] = None,
                    icon: Optional[str] = None) -> Deck:
        deck = Deck(
            owner_id=owner_id, workspace_id=workspace_id,
            name=validation.validate_deck_name(name),
            description=validation.validate_description(description),
            color=validation.validate_color(color), icon=(icon or "🎴")[:40],
            scope="manual", status="ready", stage="ready", progress=100, created_by="user",
        )
        return self.repo.create_deck(deck)

    def get_default_deck(self, owner_id: str, workspace_id: str) -> Deck:
        """Return (or lazily create) the workspace's catch-all deck for loose/manual cards."""
        decks, _ = self.repo.list_decks(owner_id, workspace_id, page_size=100, archived=ArchivedFilter.all)
        for d in decks:
            if d.name == "My Flashcards":
                return d
        return self.repo.create_deck(Deck(
            owner_id=owner_id, workspace_id=workspace_id, name="My Flashcards",
            description="Default deck for standalone and manually created cards.",
            scope="manual", status="ready", stage="ready", progress=100, created_by="user",
        ))

    def update_deck(self, deck_id: str, owner_id: str, **fields) -> Deck:
        deck = self._deck_or_404(deck_id, owner_id)
        if fields.get("name") is not None:
            deck.name = validation.validate_deck_name(fields["name"], default=deck.name)
        if fields.get("description") is not None:
            deck.description = validation.validate_description(fields["description"])
        if fields.get("color") is not None:
            deck.color = validation.validate_color(fields["color"], default=deck.color)
        if fields.get("icon") is not None:
            deck.icon = (fields["icon"] or deck.icon)[:40]
        if fields.get("is_archived") is not None:
            deck.is_archived = bool(fields["is_archived"])
        return self.repo.save_deck(deck)

    def delete_deck(self, deck_id: str, owner_id: str, *, permanent: bool = False) -> None:
        deck = self._deck_or_404(deck_id, owner_id)
        n = deck.card_count
        if permanent:
            self.repo.hard_delete_deck(deck)
        else:
            self.repo.soft_delete_deck(deck)
        self._bump_ws(deck.workspace_id, owner_id, -n)

    def get_deck(self, deck_id: str, owner_id: str) -> Deck:
        return self._deck_or_404(deck_id, owner_id)

    def list_decks(self, owner_id: str, workspace_id: str, *, with_stats: bool = True, **kw
                   ) -> Tuple[List[Deck], int, Dict[str, Dict]]:
        page = max(1, kw.pop("page", 1))
        page_size = min(max(1, kw.pop("page_size", 20)), 100)
        decks, total = self.repo.list_decks(owner_id, workspace_id, page=page, page_size=page_size, **kw)
        stats = self.repo.stats_for_decks([d.id for d in decks]) if with_stats else {}
        return decks, total, stats

    # ================================================================ AI generation (async)
    def generate_deck(self, owner_id: str, workspace_id: str, *, name: Optional[str] = None,
                      scope: Optional[str] = None, document_id: Optional[str] = None,
                      document_ids: Optional[List[str]] = None, note_id: Optional[str] = None,
                      summary_id: Optional[str] = None, conversation_id: Optional[str] = None,
                      subject: Optional[str] = None, card_type_pref: Optional[str] = None,
                      count: Optional[int] = None, deck_id: Optional[str] = None) -> Deck:
        scope = validation.validate_scope(scope, document_id=document_id, document_ids=document_ids)
        card_type_pref = validation.validate_card_type_pref(card_type_pref)
        count = validation.validate_count(count)

        if deck_id:  # append into an existing deck
            deck = self._deck_or_404(deck_id, owner_id)
            deck.scope = scope
            deck.document_id = document_id if scope == "document" else deck.document_id
            deck.document_ids = document_ids if scope == "multi" else deck.document_ids
            deck.subject = subject or deck.subject
            deck.card_type_pref = card_type_pref
            deck.target_count = count
        else:
            deck = Deck(
                owner_id=owner_id, workspace_id=workspace_id,
                name=validation.validate_deck_name(
                    name, default=validation.default_deck_name(scope, subject=subject)),
                scope=scope, document_id=document_id if scope == "document" else None,
                document_ids=document_ids if scope == "multi" else None,
                note_id=note_id, summary_id=summary_id, conversation_id=conversation_id,
                subject=subject, card_type_pref=card_type_pref, target_count=count, created_by="ai",
            )
        deck.status = "queued"
        deck.stage = "queued"
        deck.progress = 0
        deck.error = None
        # `target_count` is persisted on the row so the background runner (a fresh session) knows how
        # many cards to generate without threading it through `submit`.
        deck = self.repo.create_deck(deck) if not deck_id else self.repo.save_deck(deck)
        return deck

    def generate_now(self, deck_id: str, engine, *, count: int) -> Optional[Deck]:
        """Run generation for a queued deck (called by the runner with a trusted id)."""
        deck = self.repo.get_deck_by_id_only(deck_id)
        if deck is None:
            return None
        if deck.status == "cancelled":
            return deck

        started = time.perf_counter()
        self.repo.clear_ai_cards(deck.id)
        deck.status = "processing"
        deck.stage = "retrieving"
        deck.progress = 1
        deck.error = None
        self.repo.save_deck(deck)

        total = max(1, count)
        made = 0
        batch: List[Tuple[Flashcard, List[FlashcardCitation]]] = []
        token_usage = 0
        try:
            for ev in engine.generate(deck, self.repo.db, count=count):
                etype = ev.get("type")
                if etype == "plan":
                    if ev.get("model"):
                        deck.model_name = ev["model"]
                    total = max(1, int(ev.get("total", count)))
                    self.repo.save_deck(deck)
                elif etype == "card":
                    self.repo.db.refresh(deck)
                    if deck.status == "cancelled":
                        break
                    card, cits = self._build_card(deck, ev, created_by="ai")
                    batch.append((card, cits))
                    made += 1
                    # Flush periodically so progress + partial results are visible.
                    if len(batch) >= 5:
                        self.repo.bulk_add_cards(batch)
                        batch = []
                    deck.progress = min(99, int(made / total * 100))
                    deck.stage = f"card {made}/{total}"
                    self.repo.save_deck(deck)
                elif etype == "final":
                    token_usage = int(ev.get("token_usage", 0))
            if batch:
                self.repo.bulk_add_cards(batch)
        except Exception as e:  # failure recovery — keep whatever was flushed
            if batch:
                try:
                    self.repo.bulk_add_cards(batch)
                except Exception:
                    self.repo.db.rollback()
            deck.status = "failed"
            deck.stage = "failed"
            deck.error = str(e)[:4000]
            self.repo.recount_deck(deck.id)
            self.repo.save_deck(deck)
            return deck

        self.repo.recount_deck(deck.id)
        self._bump_ws(deck.workspace_id, deck.owner_id, made)
        if deck.status != "cancelled":
            deck.status = "completed"
            deck.stage = "completed"
            deck.progress = 100
            deck.token_usage = token_usage
            deck.generation_ms = int((time.perf_counter() - started) * 1000)
        self.repo.save_deck(deck)
        return deck

    def _build_card(self, deck: Deck, ev: Dict[str, Any], *, created_by: str) -> Tuple[Flashcard, List[FlashcardCitation]]:
        card = Flashcard(
            workspace_id=deck.workspace_id, owner_id=deck.owner_id, deck_id=deck.id,
            document_id=deck.document_id, note_id=deck.note_id, summary_id=deck.summary_id,
            conversation_id=deck.conversation_id,
            front=(ev.get("front") or "")[:4000], back=(ev.get("back") or "")[:8000],
            hint=(ev.get("hint") or "")[:1000],
            card_type=ev.get("card_type", "basic"), created_by=created_by,
        )
        cits = self._citation_rows(ev.get("citations", []) or [], deck.workspace_id)
        return card, cits

    def reset_for_regenerate(self, deck_id: str, owner_id: str, *, count: Optional[int] = None) -> Deck:
        deck = self._deck_or_404(deck_id, owner_id)
        if deck.created_by != "ai" and deck.scope == "manual":
            raise FlashcardStateError("Only AI-generated decks can be regenerated.")
        before = deck.card_count
        self.repo.clear_ai_cards(deck.id)
        after = self.repo.recount_deck(deck.id)
        self._bump_ws(deck.workspace_id, owner_id, after - before)  # exact: removed AI cards
        if count is not None:
            deck.target_count = validation.validate_count(count)
        deck.status = "queued"
        deck.stage = "queued"
        deck.progress = 0
        deck.error = None
        return self.repo.save_deck(deck)

    def cancel(self, deck_id: str, owner_id: str) -> Deck:
        deck = self._deck_or_404(deck_id, owner_id)
        if deck.status not in ("queued", "processing"):
            raise FlashcardStateError(f"Cannot cancel a '{deck.status}' deck.")
        deck.status = "cancelled"
        deck.stage = "cancelled"
        return self.repo.save_deck(deck)

    # ================================================================ cards
    def create_card(self, owner_id: str, workspace_id: str, *, deck_id: Optional[str], front: str,
                    back: Optional[str] = None, hint: Optional[str] = None, card_type: Optional[str] = None,
                    difficulty: Optional[str] = None, extra: Optional[dict] = None,
                    document_id: Optional[str] = None, note_id: Optional[str] = None,
                    summary_id: Optional[str] = None, conversation_id: Optional[str] = None,
                    citations: Optional[List[dict]] = None) -> Flashcard:
        card_type = validation.validate_card_type(card_type)
        front, back = validation.validate_card_content(front, back, card_type=card_type)
        if deck_id:
            deck = self._deck_or_404(deck_id, owner_id)
        else:
            deck = self.get_default_deck(owner_id, workspace_id)
        card = Flashcard(
            workspace_id=workspace_id, owner_id=owner_id, deck_id=deck.id,
            front=front, back=back, hint=validation.validate_hint(hint), card_type=card_type,
            difficulty=validation.validate_difficulty(difficulty), extra=extra,
            document_id=document_id, note_id=note_id, summary_id=summary_id, conversation_id=conversation_id,
            created_by="user",
        )
        rows = self._citation_rows([c if isinstance(c, dict) else c.model_dump() for c in citations], workspace_id) if citations else None
        card = self.repo.create_card(card, rows)
        self.repo.recount_deck(deck.id)
        self._bump_ws(workspace_id, owner_id, +1)
        return card

    def update_card(self, card_id: str, owner_id: str, **fields) -> Flashcard:
        card = self._card_or_404(card_id, owner_id)
        if fields.get("front") is not None or fields.get("back") is not None:
            new_type = validation.validate_card_type(fields.get("card_type") or card.card_type)
            front, back = validation.validate_card_content(
                fields.get("front", card.front), fields.get("back", card.back), card_type=new_type)
            card.front, card.back, card.card_type = front, back, new_type
        elif fields.get("card_type") is not None:
            card.card_type = validation.validate_card_type(fields["card_type"])
        if fields.get("hint") is not None:
            card.hint = validation.validate_hint(fields["hint"])
        if fields.get("difficulty") is not None:
            card.difficulty = validation.validate_difficulty(fields["difficulty"])
        if fields.get("extra") is not None:
            card.extra = fields["extra"]
        if fields.get("is_favorite") is not None:
            card.is_favorite = bool(fields["is_favorite"])
        if fields.get("deck_id") is not None and fields["deck_id"] != card.deck_id:
            dest = self._deck_or_404(fields["deck_id"], owner_id)
            old = card.deck_id
            card.deck_id = dest.id
            self.repo.save_card(card)
            self.repo.recount_deck(old)
            self.repo.recount_deck(dest.id)
            return card
        return self.repo.save_card(card)

    def suspend_card(self, card_id: str, owner_id: str, *, suspended: bool) -> Flashcard:
        card = self._card_or_404(card_id, owner_id)
        card.status = "suspended" if suspended else "active"
        return self.repo.save_card(card)

    def reset_card(self, card_id: str, owner_id: str) -> Flashcard:
        """Reset a card's SRS state to brand-new (re-learn from scratch)."""
        card = self._card_or_404(card_id, owner_id)
        card.learning_stage = "new"
        card.ease_factor = 2.5
        card.interval_days = 0
        card.repetitions = 0
        card.review_count = 0
        card.lapse_count = 0
        card.correct_count = 0
        card.mastery_score = 0.0
        card.last_reviewed_at = None
        card.next_review_at = None
        return self.repo.save_card(card)

    def delete_card(self, card_id: str, owner_id: str) -> None:
        card = self._card_or_404(card_id, owner_id)
        self.repo.soft_delete_card(card)
        self.repo.recount_deck(card.deck_id)
        self._bump_ws(card.workspace_id, owner_id, -1)

    def get_card_detail(self, card_id: str, owner_id: str):
        card = self._card_or_404(card_id, owner_id)
        cits = self.repo.citations_for([card.id]).get(card.id, [])
        return card, cits

    def list_cards(self, owner_id: str, workspace_id: str, **kw) -> Tuple[List[Flashcard], int]:
        kw["page"] = max(1, kw.get("page", 1))
        kw["page_size"] = min(max(1, kw.get("page_size", 20)), 200)
        return self.repo.list_cards(owner_id, workspace_id, **kw)

    # ================================================================ conversions
    def deck_from_source(self, owner_id: str, workspace_id: str, *, source: str, source_id: str,
                         card_type_pref: Optional[str] = None, count: Optional[int] = None) -> Deck:
        """Generate a deck from a Note / Summary / Chat conversation.

        Resolves the source's document scope (so retrieval stays grounded) + records back-links,
        then enqueues generation through the SAME pipeline as a document deck.
        """
        doc_id, subject, refs = self._resolve_source(owner_id, workspace_id, source, source_id)
        scope = "document" if doc_id else "workspace"
        return self.generate_deck(
            owner_id, workspace_id, name=validation.default_deck_name(scope, subject=subject, source=source.title()),
            scope=scope, document_id=doc_id, subject=subject,
            card_type_pref=card_type_pref, count=count, **refs,
        )

    def _resolve_source(self, owner_id: str, workspace_id: str, source: str, source_id: str):
        """Return (document_id, subject, back_link_kwargs) for a note/summary/chat source."""
        db = self.repo.db
        if source == "note":
            from app.notes.repository import NoteRepository
            note = NoteRepository(db).get(source_id, owner_id)
            if note is None or note.workspace_id != workspace_id:
                raise SourceNotFound(f"Note '{source_id}' was not found.")
            return note.document_id, note.title, {"note_id": note.id}
        if source == "summary":
            from app.summaries.repository import SummaryRepository
            s = SummaryRepository(db).get(source_id, owner_id)
            if s is None or s.workspace_id != workspace_id:
                raise SourceNotFound(f"Summary '{source_id}' was not found.")
            return s.document_id, s.title, {"summary_id": s.id}
        if source == "chat":
            from sqlalchemy import select
            from app.chat.models import Conversation
            conv = db.scalar(select(Conversation).where(Conversation.id == source_id))
            if conv is None or conv.owner_id != owner_id or conv.workspace_id != workspace_id:
                raise SourceNotFound(f"Conversation '{source_id}' was not found.")
            doc = (conv.document_scope or [None])[0] if conv.document_scope else None
            return doc, conv.title, {"conversation_id": conv.id}
        raise SourceNotFound(f"Unknown source '{source}'.")

    # ================================================================ review (SRS)
    def review_queue(self, owner_id: str, workspace_id: str, *, deck_id: Optional[str] = None,
                     limit: int = 50, new_limit: int = 20):
        if deck_id:
            self._deck_or_404(deck_id, owner_id)
        now = _now()
        cards, total_due, new_count, due_count = self.repo.review_queue(
            owner_id, workspace_id, deck_id=deck_id, now=now, limit=limit, new_limit=new_limit)
        cit_map = self.repo.citations_for([c.id for c in cards])
        return cards, cit_map, total_due, new_count, due_count

    def button_previews(self, card: Flashcard) -> Dict[str, int]:
        return preview_intervals(self._state_of(card))

    def _state_of(self, card: Flashcard) -> SRSState:
        return SRSState(
            ease_factor=card.ease_factor, interval_days=card.interval_days, repetitions=card.repetitions,
            review_count=card.review_count, lapse_count=card.lapse_count, correct_count=card.correct_count,
            learning_stage=card.learning_stage, mastery_score=card.mastery_score,
            next_review_at=card.next_review_at, last_reviewed_at=card.last_reviewed_at,
        )

    def submit_review(self, card_id: str, owner_id: str, *, rating: str, response_time_ms: int = 0) -> Flashcard:
        card = self._card_or_404(card_id, owner_id)
        if card.status != "active":
            raise FlashcardStateError(f"Cannot review a '{card.status}' card.")
        rating = validation.validate_rating(rating)
        now = _now()
        result = schedule(self._state_of(card), rating, now=now)
        ns = result.state

        # Persist the SRS outputs onto the card.
        card.ease_factor = ns.ease_factor
        card.interval_days = ns.interval_days
        card.repetitions = ns.repetitions
        card.review_count = ns.review_count
        card.lapse_count = ns.lapse_count
        card.correct_count = ns.correct_count
        card.learning_stage = ns.learning_stage
        card.mastery_score = ns.mastery_score
        card.last_reviewed_at = ns.last_reviewed_at
        card.next_review_at = ns.next_review_at
        self.repo.save_card(card)

        # Append the immutable review event (powers analytics).
        self.repo.add_review(FlashcardReview(
            flashcard_id=card.id, deck_id=card.deck_id, workspace_id=card.workspace_id, owner_id=owner_id,
            rating=rating, quality_score=result.quality, response_time_ms=max(0, int(response_time_ms)),
            was_correct=result.was_correct, prev_interval=result.prev_interval,
            scheduled_interval=result.scheduled_interval, ease_factor=ns.ease_factor, review_date=now,
        ))
        return card

    # ================================================================ analytics
    def analytics(self, owner_id: str, workspace_id: str, *, days: int = 30) -> Dict:
        return self.repo.analytics(owner_id, workspace_id, days=days)

    def deck_stats(self, deck_id: str, owner_id: str) -> Dict:
        self._deck_or_404(deck_id, owner_id)
        return self.repo.deck_stats(deck_id)
