"""Flashcard HTTP routes — thin transport over FlashcardService + a background runner.

Authenticated + workspace-scoped. Manual decks/cards are created synchronously; AI generation is
asynchronous (create returns a `queued` deck; the client polls `GET .../status`). The generation
runner is injected (lazily) so `app.flashcards.api` imports with no faiss/torch and tests substitute
an inline runner + fake engine.
"""

from __future__ import annotations

import csv
import io
from math import ceil

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.flashcards.errors import FlashcardError
from app.flashcards.repository import FlashcardRepository
from app.flashcards.schemas import (
    ArchivedFilter,
    CardCreate,
    CardSortField,
    CardStatusFilter,
    CardUpdate,
    DailyActivity,
    DeckCreate,
    DeckGenerate,
    DeckListResponse,
    DeckOut,
    DeckSortField,
    DeckStats,
    DeckWithStats,
    FlashcardCitationOut,
    FlashcardDetail,
    FlashcardListResponse,
    FlashcardOut,
    LearningAnalytics,
    ReviewButton,
    ReviewCard,
    ReviewQueue,
    ReviewResult,
    ReviewSubmit,
    SortOrder,
)
from app.flashcards.service import FlashcardService
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["flashcards"])

_runner = None


def get_flashcards_runner():
    global _runner
    if _runner is None:
        from app.flashcards.runner import FlashcardRunner
        _runner = FlashcardRunner()
    return _runner


def _service(db: Session) -> FlashcardService:
    return FlashcardService(FlashcardRepository(db), WorkspaceService(WorkspaceRepository(db)))


def _handle(fn):
    try:
        return fn()
    except FlashcardError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _deck_out(deck, stats: dict | None = None) -> DeckWithStats:
    d = DeckWithStats.model_validate(deck)
    if stats is not None:
        d.stats = DeckStats(**stats)
    return d


def _card_out(card) -> FlashcardOut:
    return FlashcardOut.model_validate(card)


def _card_detail(card, cits) -> FlashcardDetail:
    d = FlashcardDetail.model_validate(card)
    d.citations = [FlashcardCitationOut.model_validate(c) for c in cits]
    return d


# ============================================================ decks: create / generate
@router.post("/decks", response_model=DeckOut, status_code=201)
def create_deck(workspace_id: str, req: DeckCreate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    deck = _handle(lambda: _service(db).create_deck(
        owner_id, workspace_id, name=req.name, description=req.description, color=req.color, icon=req.icon))
    return DeckOut.model_validate(deck)


@router.post("/decks/generate", response_model=DeckOut, status_code=202)
def generate_deck(workspace_id: str, req: DeckGenerate, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db), runner=Depends(get_flashcards_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    deck = _handle(lambda: _service(db).generate_deck(
        owner_id, workspace_id, name=req.name, scope=req.scope, document_id=req.document_id,
        document_ids=req.document_ids, note_id=req.note_id, summary_id=req.summary_id,
        conversation_id=req.conversation_id, subject=req.subject, card_type_pref=req.card_type_pref,
        count=req.count, deck_id=req.deck_id))
    runner.submit(deck.id)
    db.refresh(deck)
    return DeckOut.model_validate(deck)


def _from_source(source: str):
    def endpoint(workspace_id: str, source_id: str,
                 card_type_pref: str | None = Query(None), count: int | None = Query(None),
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                 runner=Depends(get_flashcards_runner)):
        _verify_workspace(db, workspace_id, owner_id)
        deck = _handle(lambda: _service(db).deck_from_source(
            owner_id, workspace_id, source=source, source_id=source_id,
            card_type_pref=card_type_pref, count=count))
        runner.submit(deck.id)
        db.refresh(deck)
        return DeckOut.model_validate(deck)
    return endpoint


router.add_api_route("/decks/from-note/{source_id}", _from_source("note"), methods=["POST"], response_model=DeckOut, status_code=202)
router.add_api_route("/decks/from-summary/{source_id}", _from_source("summary"), methods=["POST"], response_model=DeckOut, status_code=202)
router.add_api_route("/decks/from-chat/{source_id}", _from_source("chat"), methods=["POST"], response_model=DeckOut, status_code=202)


# ============================================================ decks: list / read
@router.get("/decks", response_model=DeckListResponse)
def list_decks(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               search: str | None = Query(None), archived: ArchivedFilter = Query(ArchivedFilter.active),
               sort_by: DeckSortField = Query(DeckSortField.updated_at), order: SortOrder = Query(SortOrder.desc)):
    _verify_workspace(db, workspace_id, owner_id)
    decks, total, stats = _service(db).list_decks(
        owner_id, workspace_id, page=page, page_size=page_size, search=search,
        archived=archived, sort_by=sort_by, order=order)
    return DeckListResponse(
        items=[_deck_out(d, stats.get(d.id)) for d in decks], total=total, page=page,
        page_size=page_size, pages=ceil(total / page_size) if page_size else 0)


@router.get("/decks/{deck_id}", response_model=DeckWithStats)
def get_deck(workspace_id: str, deck_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    svc = _service(db)
    deck = _handle(lambda: svc.get_deck(deck_id, owner_id))
    return _deck_out(deck, svc.deck_stats(deck_id, owner_id))


@router.get("/decks/{deck_id}/status", response_model=DeckOut)
def deck_status(workspace_id: str, deck_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return DeckOut.model_validate(_handle(lambda: _service(db).get_deck(deck_id, owner_id)))


@router.patch("/decks/{deck_id}", response_model=DeckOut)
def update_deck(workspace_id: str, deck_id: str, req: DeckUpdate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    deck = _handle(lambda: _service(db).update_deck(
        deck_id, owner_id, name=req.name, description=req.description, color=req.color,
        icon=req.icon, is_archived=req.is_archived))
    return DeckOut.model_validate(deck)


@router.post("/decks/{deck_id}/regenerate", response_model=DeckOut)
def regenerate_deck(workspace_id: str, deck_id: str, count: int | None = Query(None),
                    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                    runner=Depends(get_flashcards_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    deck = _handle(lambda: _service(db).reset_for_regenerate(deck_id, owner_id, count=count))
    runner.submit(deck.id)
    db.refresh(deck)
    return DeckOut.model_validate(deck)


@router.post("/decks/{deck_id}/cancel", response_model=DeckOut)
def cancel_deck(workspace_id: str, deck_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return DeckOut.model_validate(_handle(lambda: _service(db).cancel(deck_id, owner_id)))


@router.delete("/decks/{deck_id}", status_code=204)
def delete_deck(workspace_id: str, deck_id: str, permanent: bool = Query(False),
                owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete_deck(deck_id, owner_id, permanent=permanent))
    return None


# ============================================================ decks: export / import
@router.get("/decks/{deck_id}/export")
def export_deck(workspace_id: str, deck_id: str, format: str = Query("csv", pattern="^(csv|md|markdown)$"),
                owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    svc = _service(db)
    deck = _handle(lambda: svc.get_deck(deck_id, owner_id))
    cards, _ = svc.list_cards(owner_id, workspace_id, deck_id=deck_id, page_size=200)
    safe = (deck.name or "deck").replace('"', "").replace("/", "-")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["front", "back", "hint", "card_type"])
        for c in cards:
            w.writerow([c.front, c.back, c.hint, c.card_type])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})
    lines = [f"# {deck.name}", ""]
    for c in cards:
        lines += [f"### {c.front}", "", c.back, ""]
        if c.hint:
            lines.append(f"> Hint: {c.hint}")
        lines.append("")
    return Response(content="\n".join(lines), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})


@router.post("/decks/{deck_id}/import", response_model=DeckOut)
def import_cards(workspace_id: str, deck_id: str, payload: dict = Body(...),
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Import cards from delimited text: one card per line as `front <TAB or |> back <TAB or |> hint`."""
    _verify_workspace(db, workspace_id, owner_id)
    svc = _service(db)
    deck = _handle(lambda: svc.get_deck(deck_id, owner_id))
    text = str(payload.get("text", ""))
    made = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split("|"))]
        if len(parts) < 2 or not parts[0]:
            continue
        front, back = parts[0], parts[1]
        hint = parts[2] if len(parts) > 2 else None
        try:
            svc.create_card(owner_id, workspace_id, deck_id=deck.id, front=front, back=back, hint=hint)
            made += 1
        except FlashcardError:
            continue
    db.refresh(deck)
    return DeckOut.model_validate(deck)


# ============================================================ cards: CRUD
@router.post("/flashcards", response_model=FlashcardDetail, status_code=201)
def create_card(workspace_id: str, req: CardCreate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    svc = _service(db)
    card = _handle(lambda: svc.create_card(
        owner_id, workspace_id, deck_id=req.deck_id, front=req.front, back=req.back, hint=req.hint,
        card_type=req.card_type, difficulty=req.difficulty, extra=req.extra, document_id=req.document_id,
        note_id=req.note_id, summary_id=req.summary_id, conversation_id=req.conversation_id,
        citations=[c.model_dump() for c in req.citations] if req.citations else None))
    _, cits = svc.get_card_detail(card.id, owner_id)
    return _card_detail(card, cits)


@router.get("/flashcards", response_model=FlashcardListResponse)
def list_cards(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
               deck_id: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200),
               search: str | None = Query(None), card_type: str | None = Query(None),
               status: CardStatusFilter = Query(CardStatusFilter.any), favorite: bool | None = Query(None),
               sort_by: CardSortField = Query(CardSortField.created_at), order: SortOrder = Query(SortOrder.desc)):
    _verify_workspace(db, workspace_id, owner_id)
    items, total = _service(db).list_cards(
        owner_id, workspace_id, deck_id=deck_id, page=page, page_size=page_size, search=search,
        card_type=card_type, status=status, favorite=favorite, sort_by=sort_by, order=order)
    return FlashcardListResponse(
        items=[_card_out(c) for c in items], total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0)


@router.get("/flashcards/{card_id}", response_model=FlashcardDetail)
def get_card(workspace_id: str, card_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    card, cits = _handle(lambda: _service(db).get_card_detail(card_id, owner_id))
    return _card_detail(card, cits)


@router.patch("/flashcards/{card_id}", response_model=FlashcardOut)
def update_card(workspace_id: str, card_id: str, req: CardUpdate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    card = _handle(lambda: _service(db).update_card(
        card_id, owner_id, front=req.front, back=req.back, hint=req.hint, card_type=req.card_type,
        difficulty=req.difficulty, extra=req.extra, is_favorite=req.is_favorite, deck_id=req.deck_id))
    return _card_out(card)


@router.post("/flashcards/{card_id}/suspend", response_model=FlashcardOut)
def suspend_card(workspace_id: str, card_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _card_out(_handle(lambda: _service(db).suspend_card(card_id, owner_id, suspended=True)))


@router.post("/flashcards/{card_id}/unsuspend", response_model=FlashcardOut)
def unsuspend_card(workspace_id: str, card_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _card_out(_handle(lambda: _service(db).suspend_card(card_id, owner_id, suspended=False)))


@router.post("/flashcards/{card_id}/reset", response_model=FlashcardOut)
def reset_card(workspace_id: str, card_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _card_out(_handle(lambda: _service(db).reset_card(card_id, owner_id)))


@router.delete("/flashcards/{card_id}", status_code=204)
def delete_card(workspace_id: str, card_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete_card(card_id, owner_id))
    return None


# ============================================================ review (SRS)
@router.get("/review", response_model=ReviewQueue)
def get_review_queue(workspace_id: str, deck_id: str | None = Query(None), limit: int = Query(50, ge=1, le=200),
                     new_limit: int = Query(20, ge=0, le=100),
                     owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    svc = _service(db)
    cards, cit_map, total_due, new_count, due_count = _handle(lambda: svc.review_queue(
        owner_id, workspace_id, deck_id=deck_id, limit=limit, new_limit=new_limit))
    review_cards = []
    for c in cards:
        previews = svc.button_previews(c)
        buttons = [ReviewButton(rating=r, interval_days=previews[r], label=_interval_label(previews[r]))
                   for r in ("again", "hard", "good", "easy")]
        review_cards.append(ReviewCard(card=_card_detail(c, cit_map.get(c.id, [])), buttons=buttons))
    return ReviewQueue(deck_id=deck_id, total_due=total_due, new_count=new_count,
                       due_count=due_count, cards=review_cards)


@router.post("/flashcards/{card_id}/review", response_model=ReviewResult)
def submit_review(workspace_id: str, card_id: str, req: ReviewSubmit,
                  owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    card = _handle(lambda: _service(db).submit_review(
        card_id, owner_id, rating=req.rating, response_time_ms=req.response_time_ms or 0))
    return ReviewResult(card=_card_out(card), rating=req.rating, scheduled_interval=card.interval_days,
                        next_review_at=card.next_review_at, mastery_score=card.mastery_score)


# ============================================================ analytics
@router.get("/analytics", response_model=LearningAnalytics)
def learning_analytics(workspace_id: str, days: int = Query(30, ge=1, le=365),
                       owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    data = _service(db).analytics(owner_id, workspace_id, days=days)
    data["daily_activity"] = [DailyActivity(**d) for d in data["daily_activity"]]
    return LearningAnalytics(**data)


@router.get("/decks/{deck_id}/stats", response_model=DeckStats)
def deck_statistics(workspace_id: str, deck_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return DeckStats(**_handle(lambda: _service(db).deck_stats(deck_id, owner_id)))


def _interval_label(days: int) -> str:
    if days <= 0:
        return "<1d"
    if days == 1:
        return "1d"
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{round(days / 365, 1)}y"
