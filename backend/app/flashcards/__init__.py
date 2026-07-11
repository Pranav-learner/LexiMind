"""Flashcards domain module (Phase 3, Module 7: AI Flashcards & Active Recall Learning Engine).

Turns LexiMind from a knowledge platform into a learning platform: persistent flashcards, generated
from any source (document/note/summary/chat/selection/manual) via the SAME retrieval→context→LLM
pipeline, scheduled with a scientifically-backed spaced-repetition algorithm (SM-2 variant), and
fully citation-aware. Layered like the other domain packages:

    models.py       Deck / Flashcard / FlashcardCitation / FlashcardReview ORM (4 new tables)
    scheduler.py    the pure SM-2 SRS engine (rating → new schedule); no DB, no clock
    schemas.py      DTOs + list query enums
    validation.py   pure deck/card/rating/scope validation
    errors.py       transport-agnostic domain errors
    repository.py   all SQL (owner+workspace scoped, soft-delete aware) + stats/queue/analytics
    engine.py       the ONLY bridge to the AI pipeline (retrieval→context→LLM→parse), injected
    service.py      decks + cards + generation pipeline + SRS review + analytics
    runner.py       background execution (threadpool prod runner + inline test runner)
    api.py          authenticated routes under /workspaces/{id}/decks, /flashcards, /review, /analytics

Business logic never lives in API handlers; the API never issues SQL directly; the package never
imports faiss (the engine is injected) and NEVER implements its own retrieval/context.
"""
