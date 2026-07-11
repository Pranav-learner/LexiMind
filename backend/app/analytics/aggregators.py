"""The statistics & analytics engine — a registry of independently-extensible dashboard widgets.

Each widget is a pure-ish function `(AggContext) -> JSON-safe dict` registered by key via `@widget`.
The service computes/caches widgets by key. FUTURE MODULES add a dashboard widget by importing
`widget` and decorating a new function — no existing code changes (the extensibility requirement).

Every widget only READS other modules' rows (documents, chat, summaries, notes, flashcards,
citations, reading sessions) — it never mutates them and never touches the retrieval pipeline.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# The widget registry. section key -> compute function.
WIDGETS: Dict[str, Callable[["AggContext"], dict]] = {}


def widget(key: str):
    def deco(fn: Callable[["AggContext"], dict]):
        WIDGETS[key] = fn
        return fn
    return deco


@dataclass
class AggContext:
    db: Session
    workspace_id: str
    owner_id: str
    now: datetime


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _day(dt) -> str:
    return dt.date().isoformat()


# ==================================================================== knowledge
@widget("knowledge")
def knowledge_stats(ctx: AggContext) -> dict:
    from app.documents.models import Document
    from app.workspaces.models import Workspace

    ws = ctx.db.get(Workspace, ctx.workspace_id)
    docs = list(ctx.db.scalars(
        select(Document).where(Document.workspace_id == ctx.workspace_id, Document.deleted_at.is_(None))
    ))
    active = [d for d in docs if not d.is_archived]
    pages = sum(d.page_count for d in active)
    chunks = sum(d.chunk_count for d in active)
    words = sum(d.word_count for d in active)
    storage = sum(d.file_size for d in active)
    ready = sum(1 for d in active if d.processing_status == "ready")
    indexed = sum(1 for d in active if d.indexing_status == "indexed")

    langs = Counter(d.language for d in active if d.language)
    embedding_model = next((d.embedding_model for d in active if d.embedding_model), "")
    if not embedding_model:
        from app.core.config import settings
        embedding_model = settings.embedding_model

    # Heuristic "topics": most common significant tokens across document names.
    stop = {"the", "and", "for", "with", "notes", "pdf", "doc", "document", "final", "draft", "chapter"}
    tokens = Counter()
    for d in active:
        for t in (d.display_name or "").lower().replace("_", " ").replace("-", " ").split():
            t = "".join(ch for ch in t if ch.isalnum())
            if len(t) >= 4 and t not in stop and not t.isdigit():
                tokens[t] += 1
    topics = [t.title() for t, _ in tokens.most_common(8)]

    recent = sorted(active, key=lambda d: d.created_at or ctx.now, reverse=True)[:5]

    index_health = "healthy" if ready and indexed >= ready else ("degraded" if ready else "empty")
    retrieval_health = "healthy" if chunks > 0 else "empty"

    return {
        "workspace_name": ws.name if ws else "Workspace",
        "documents": len(active),
        "archived_documents": len(docs) - len(active),
        "pages": pages, "chunks": chunks, "embeddings": chunks, "words": words,
        "storage_bytes": storage,
        "indexed_files": indexed, "ready_files": ready,
        "avg_document_bytes": storage // len(active) if active else 0,
        "embedding_model": embedding_model,
        "languages": [{"language": lang, "count": n} for lang, n in langs.most_common()],
        "topics": topics,
        "recent_uploads": [
            {"id": d.id, "display_name": d.display_name, "created_at": _iso(d.created_at),
             "page_count": d.page_count, "processing_status": d.processing_status}
            for d in recent
        ],
        "index_health": index_health,
        "retrieval_health": retrieval_health,
        "context_engine_health": "healthy",
    }


# ==================================================================== ai usage
def _assistant_message_agg(ctx: AggContext):
    from app.chat.models import Conversation, Message
    return ctx.db.execute(
        select(func.count(), func.coalesce(func.avg(Message.latency_ms), 0),
               func.coalesce(func.avg(Message.retrieval_ms), 0),
               func.coalesce(func.avg(Message.context_size), 0),
               func.coalesce(func.avg(Message.token_usage), 0),
               func.coalesce(func.sum(Message.token_usage), 0))
        .select_from(Message).join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.workspace_id == ctx.workspace_id, Message.role == "assistant")
    ).one()


def _source_citation_count(ctx: AggContext, *, message_only: bool = False, document_id: str | None = None) -> int:
    """Count raw citations across the 4 source tables (index-independent)."""
    from app.chat.models import MessageCitation
    from app.flashcards.models import FlashcardCitation
    from app.notes.models import NoteCitation
    from app.summaries.models import SummaryCitation

    def c(model):
        conds = [model.workspace_id == ctx.workspace_id]
        if document_id is not None:
            conds.append(model.document_id == document_id)
        return ctx.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0

    if message_only:
        return int(c(MessageCitation))
    return int(c(MessageCitation) + c(SummaryCitation) + c(NoteCitation) + c(FlashcardCitation))


@widget("ai_usage")
def ai_usage(ctx: AggContext) -> dict:
    from app.chat.models import Conversation, Message
    from app.flashcards.models import Deck, Flashcard
    from app.notes.models import Note
    from app.summaries.models import Summary

    conversations = ctx.db.scalar(select(func.count()).select_from(Conversation)
                                  .where(Conversation.workspace_id == ctx.workspace_id, Conversation.deleted_at.is_(None))) or 0
    messages = ctx.db.scalar(select(func.count()).select_from(Message)
                             .join(Conversation, Conversation.id == Message.conversation_id)
                             .where(Conversation.workspace_id == ctx.workspace_id)) or 0
    questions = ctx.db.scalar(select(func.count()).select_from(Message)
                              .join(Conversation, Conversation.id == Message.conversation_id)
                              .where(Conversation.workspace_id == ctx.workspace_id, Message.role == "user")) or 0

    n_asst, avg_lat, avg_ret, avg_ctx, avg_tok, total_tok = _assistant_message_agg(ctx)

    summaries = ctx.db.scalar(select(func.count()).select_from(Summary)
                              .where(Summary.workspace_id == ctx.workspace_id, Summary.deleted_at.is_(None))) or 0
    notes = ctx.db.scalar(select(func.count()).select_from(Note)
                          .where(Note.workspace_id == ctx.workspace_id, Note.deleted_at.is_(None))) or 0
    flashcards = ctx.db.scalar(select(func.count()).select_from(Flashcard)
                               .where(Flashcard.workspace_id == ctx.workspace_id, Flashcard.deleted_at.is_(None))) or 0

    # Model usage across conversations, summaries, decks.
    models = Counter()
    for (m,) in ctx.db.execute(select(Conversation.model_name).where(Conversation.workspace_id == ctx.workspace_id)).all():
        if m:
            models[m] += 1
    for (m,) in ctx.db.execute(select(Summary.model_name).where(Summary.workspace_id == ctx.workspace_id)).all():
        if m:
            models[m] += 1
    for (m,) in ctx.db.execute(select(Deck.model_name).where(Deck.workspace_id == ctx.workspace_id)).all():
        if m:
            models[m] += 1

    return {
        "questions_asked": int(questions), "conversations": int(conversations), "messages": int(messages),
        "summaries_generated": int(summaries), "notes_generated": int(notes), "flashcards_generated": int(flashcards),
        "citation_usage": _source_citation_count(ctx),
        "avg_response_time_ms": int(avg_lat), "avg_retrieval_ms": int(avg_ret),
        "avg_context_size": int(avg_ctx), "avg_token_usage": int(avg_tok),
        "estimated_cost_usd": 0.0,  # local model — future-ready hook for hosted pricing
        "total_tokens": int(total_tok),
        "model_usage": [{"model": m, "count": n} for m, n in models.most_common()],
    }


# ==================================================================== learning
@widget("learning")
def learning_stats(ctx: AggContext) -> dict:
    from app.documents.models import Document, ReadingSession
    from app.flashcards.repository import FlashcardRepository
    from app.notes.models import Note
    from app.summaries.models import Summary

    fa = FlashcardRepository(ctx.db).analytics(ctx.owner_id, ctx.workspace_id, days=30)

    notes = ctx.db.scalar(select(func.count()).select_from(Note)
                          .where(Note.workspace_id == ctx.workspace_id, Note.deleted_at.is_(None))) or 0
    summaries = ctx.db.scalar(select(func.count()).select_from(Summary)
                              .where(Summary.workspace_id == ctx.workspace_id, Summary.deleted_at.is_(None))) or 0
    reading_minutes = ctx.db.scalar(select(func.coalesce(func.sum(Note.reading_time), 0))
                                    .where(Note.workspace_id == ctx.workspace_id, Note.deleted_at.is_(None))) or 0

    # Documents "completed" = a reading session at/after the last page.
    completed = 0
    for rs, doc in ctx.db.execute(
        select(ReadingSession, Document)
        .join(Document, Document.id == ReadingSession.document_id)
        .where(ReadingSession.workspace_id == ctx.workspace_id, ReadingSession.owner_id == ctx.owner_id)
    ).all():
        if doc.page_count and rs.page >= doc.page_count:
            completed += 1

    return {
        "study_streak_days": fa["study_streak_days"], "cards_reviewed": fa["reviews_total"],
        "reviews_today": fa["reviews_today"], "retention": fa["retention"], "accuracy": fa["accuracy"],
        "avg_mastery": fa["avg_mastery"], "mastered_cards": fa["mastered_cards"], "due_today": fa["due_today"],
        "new_cards": fa["new_cards"], "notes_created": int(notes), "summaries_created": int(summaries),
        "documents_completed": completed, "reading_minutes": int(reading_minutes),
        "daily_activity": fa["daily_activity"],
    }


# ==================================================================== documents
@widget("documents")
def document_analytics(ctx: AggContext) -> dict:
    return {"items": [_document_analytics_row(ctx, d) for d in _workspace_documents(ctx)]}


def _workspace_documents(ctx: AggContext):
    from app.documents.models import Document
    return list(ctx.db.scalars(
        select(Document).where(Document.workspace_id == ctx.workspace_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    ))


def _document_analytics_row(ctx: AggContext, d) -> dict:
    from app.documents.models import ReadingSession
    from app.flashcards.models import Flashcard
    from app.notes.models import Note
    from app.summaries.models import Summary
    from app.chat.models import MessageCitation
    from app.summaries.models import SummaryCitation
    from app.notes.models import NoteCitation
    from app.flashcards.models import FlashcardCitation

    vid = d.vector_document_id
    citation_count = _source_citation_count(ctx, document_id=vid)
    question_frequency = _source_citation_count(ctx, message_only=True, document_id=vid)

    summaries = ctx.db.scalar(select(func.count()).select_from(Summary)
                              .where(Summary.workspace_id == ctx.workspace_id, Summary.document_id == d.id, Summary.deleted_at.is_(None))) or 0
    notes = ctx.db.scalar(select(func.count()).select_from(Note)
                          .where(Note.workspace_id == ctx.workspace_id, Note.document_id == d.id, Note.deleted_at.is_(None))) or 0
    flashcards = ctx.db.scalar(select(func.count()).select_from(Flashcard)
                               .where(Flashcard.workspace_id == ctx.workspace_id, Flashcard.document_id == d.id, Flashcard.deleted_at.is_(None))) or 0

    rs = ctx.db.scalar(select(ReadingSession).where(
        ReadingSession.workspace_id == ctx.workspace_id, ReadingSession.owner_id == ctx.owner_id,
        ReadingSession.document_id == d.id))
    page = rs.page if rs else 0
    progress = round(min(1.0, page / d.page_count), 4) if d.page_count else 0.0

    # Most-cited pages (a proxy for "most viewed sections").
    page_counter = Counter()
    for model in (MessageCitation, SummaryCitation, NoteCitation, FlashcardCitation):
        for (pg,) in ctx.db.execute(
            select(model.page_number).where(model.workspace_id == ctx.workspace_id, model.document_id == vid, model.page_number.is_not(None))
        ).all():
            page_counter[pg] += 1
    top_pages = [{"page": pg, "count": n} for pg, n in page_counter.most_common(3)]

    return {
        "id": d.id, "display_name": d.display_name, "vector_document_id": vid,
        "pages": d.page_count, "chunks": d.chunk_count, "embeddings": d.chunk_count,
        "words": d.word_count, "file_size": d.file_size, "language": d.language,
        "citation_count": citation_count, "retrieval_frequency": citation_count,
        "question_frequency": question_frequency,
        "summaries": int(summaries), "notes": int(notes), "flashcards": int(flashcards),
        "reading_page": page, "reading_progress": progress,
        "completed": bool(d.page_count and page >= d.page_count),
        "last_opened": _iso(rs.updated_at) if rs else None,
        "top_pages": top_pages, "created_at": _iso(d.created_at),
    }


# ==================================================================== retrieval
@widget("retrieval")
def retrieval_analytics(ctx: AggContext) -> dict:
    from app.core.config import settings

    n_asst, avg_lat, avg_ret, avg_ctx, avg_tok, _total = _assistant_message_agg(ctx)
    utilization = round(float(avg_ctx) / settings.context_window, 4) if settings.context_window else 0.0
    return {
        "hybrid_enabled": True, "dense_enabled": True, "bm25_enabled": True, "rrf_enabled": True,
        "reranker_enabled": bool(settings.enable_reranker), "compression_enabled": bool(settings.enable_compression),
        "dense_top_k": settings.dense_top_k, "sparse_top_k": settings.sparse_top_k,
        "final_top_k": settings.final_top_k, "rrf_k": settings.rrf_k,
        "dedup_threshold": settings.dedup_threshold, "context_window": settings.context_window,
        "embedding_model": settings.embedding_model,
        "avg_retrieval_ms": int(avg_ret), "avg_context_size": int(avg_ctx),
        "context_utilization": utilization, "retrieved_answers": int(n_asst),
        "note": "Recall/precision/MRR are measured by the offline evaluation harness on labelled "
                "data; runtime latency + context utilization are shown here.",
    }


# ==================================================================== activity timeline
@widget("activity")
def activity_timeline(ctx: AggContext) -> dict:
    from app.chat.models import Conversation
    from app.documents.models import Document
    from app.flashcards.models import Deck, Flashcard, FlashcardReview
    from app.notes.models import Note
    from app.summaries.models import Summary

    events: List[dict] = []

    def add(rows, type_, icon, title_fn, route_fn, ts_attr="created_at"):
        for r in rows:
            events.append({"type": type_, "icon": icon, "title": title_fn(r),
                           "timestamp": _iso(getattr(r, ts_attr)), "target_id": r.id, "route": route_fn(r)})

    ws = ctx.workspace_id
    add(ctx.db.scalars(select(Document).where(Document.workspace_id == ws, Document.deleted_at.is_(None)).order_by(Document.created_at.desc()).limit(15)),
        "document", "📄", lambda d: f"Uploaded “{d.display_name}”", lambda d: f"/workspace/{ws}/document/{d.id}")
    add(ctx.db.scalars(select(Summary).where(Summary.workspace_id == ws, Summary.deleted_at.is_(None)).order_by(Summary.created_at.desc()).limit(10)),
        "summary", "📝", lambda s: f"Generated summary “{s.title}”", lambda s: f"/workspace/{ws}/summaries/{s.id}")
    add(ctx.db.scalars(select(Note).where(Note.workspace_id == ws, Note.deleted_at.is_(None)).order_by(Note.created_at.desc()).limit(10)),
        "note", "🗒", lambda n: f"Created note “{n.title}”", lambda n: f"/workspace/{ws}/notes/{n.id}")
    add(ctx.db.scalars(select(Conversation).where(Conversation.workspace_id == ws, Conversation.deleted_at.is_(None)).order_by(Conversation.created_at.desc()).limit(10)),
        "chat", "💬", lambda c: f"Started chat “{c.title}”", lambda c: f"/workspace/{ws}/chat/{c.id}")
    add(ctx.db.scalars(select(Deck).where(Deck.workspace_id == ws, Deck.deleted_at.is_(None)).order_by(Deck.created_at.desc()).limit(10)),
        "deck", "🎴", lambda d: f"Created deck “{d.name}”", lambda d: f"/workspace/{ws}/flashcards/deck/{d.id}")

    # Flashcard reviews (recent) — join to name the deck.
    for rev, deck in ctx.db.execute(
        select(FlashcardReview, Deck).join(Deck, Deck.id == FlashcardReview.deck_id)
        .where(FlashcardReview.workspace_id == ws).order_by(FlashcardReview.review_date.desc()).limit(15)
    ).all():
        events.append({"type": "review", "icon": "✅", "title": f"Reviewed a card in “{deck.name}”",
                       "timestamp": _iso(rev.review_date), "target_id": deck.id,
                       "route": f"/workspace/{ws}/flashcards/deck/{deck.id}"})

    events.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    return {"items": events[:40]}


# ==================================================================== charts
@widget("charts")
def charts(ctx: AggContext) -> dict:
    from app.chat.models import Conversation, Message
    from app.documents.models import Document
    from app.flashcards.models import Flashcard, FlashcardReview
    from app.notes.models import Note
    from app.summaries.models import Summary

    days = 30
    today = ctx.now.date()
    day_keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    activity = {k: 0 for k in day_keys}
    ai = {k: 0 for k in day_keys}

    def bump(dmap, rows):
        for (ts,) in rows:
            if ts is None:
                continue
            k = _day(ts)
            if k in dmap:
                dmap[k] += 1

    ws = ctx.workspace_id
    bump(activity, ctx.db.execute(select(Document.created_at).where(Document.workspace_id == ws, Document.deleted_at.is_(None))).all())
    bump(activity, ctx.db.execute(select(Note.created_at).where(Note.workspace_id == ws, Note.deleted_at.is_(None))).all())
    bump(activity, ctx.db.execute(select(Summary.created_at).where(Summary.workspace_id == ws, Summary.deleted_at.is_(None))).all())
    bump(activity, ctx.db.execute(select(FlashcardReview.review_date).where(FlashcardReview.workspace_id == ws)).all())
    bump(ai, ctx.db.execute(select(Message.created_at).join(Conversation, Conversation.id == Message.conversation_id)
                            .where(Conversation.workspace_id == ws)).all())
    # AI activity also counts toward the overall heatmap.
    for k in day_keys:
        activity[k] += ai[k]

    # Cumulative knowledge growth (documents) over the window.
    doc_dates = sorted(_day(ts) for (ts,) in ctx.db.execute(
        select(Document.created_at).where(Document.workspace_id == ws, Document.deleted_at.is_(None))).all() if ts)
    cum = 0
    growth = []
    di = 0
    for k in day_keys:
        while di < len(doc_dates) and doc_dates[di] <= k:
            cum += 1
            di += 1
        growth.append({"date": k, "value": cum})

    # Distributions.
    def cnt(model, *conds):
        return int(ctx.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0)
    dist = [
        {"label": "Documents", "value": cnt(Document, Document.workspace_id == ws, Document.deleted_at.is_(None))},
        {"label": "Chats", "value": cnt(Conversation, Conversation.workspace_id == ws, Conversation.deleted_at.is_(None))},
        {"label": "Notes", "value": cnt(Note, Note.workspace_id == ws, Note.deleted_at.is_(None))},
        {"label": "Summaries", "value": cnt(Summary, Summary.workspace_id == ws, Summary.deleted_at.is_(None))},
        {"label": "Flashcards", "value": cnt(Flashcard, Flashcard.workspace_id == ws, Flashcard.deleted_at.is_(None))},
    ]

    # Flashcard learning distribution.
    from app.flashcards.repository import FlashcardRepository, MASTERY_THRESHOLD
    cards = list(ctx.db.scalars(select(Flashcard).where(Flashcard.workspace_id == ws, Flashcard.deleted_at.is_(None), Flashcard.status == "active")))
    fc_new = sum(1 for c in cards if c.next_review_at is None)
    fc_mastered = sum(1 for c in cards if c.mastery_score >= MASTERY_THRESHOLD)
    fc_learning = len(cards) - fc_new - fc_mastered
    _ = FlashcardRepository  # (imported for MASTERY_THRESHOLD alongside)

    return {
        "series": [
            {"key": "daily_activity", "label": "Daily activity", "kind": "heatmap",
             "points": [{"date": k, "value": activity[k]} for k in day_keys]},
            {"key": "activity_line", "label": "Activity (30d)", "kind": "line",
             "points": [{"date": k, "value": activity[k]} for k in day_keys]},
            {"key": "ai_usage", "label": "AI messages (30d)", "kind": "line",
             "points": [{"date": k, "value": ai[k]} for k in day_keys]},
            {"key": "knowledge_growth", "label": "Knowledge growth", "kind": "line", "points": growth},
            {"key": "asset_distribution", "label": "Workspace distribution", "kind": "donut", "points": dist},
            {"key": "flashcard_progress", "label": "Flashcard progress", "kind": "donut",
             "points": [{"label": "New", "value": fc_new}, {"label": "Learning", "value": max(0, fc_learning)},
                        {"label": "Mastered", "value": fc_mastered}]},
        ]
    }
