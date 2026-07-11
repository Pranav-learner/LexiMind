"""Notes domain module (Phase 3, Module 6: Smart Notes Engine).

Persistent, editable, user-owned knowledge assets. Unlike a Summary (a read-only AI output), a
Note is a first-class document the user keeps editing — the seed of a personal knowledge base.
Layered like the other domain packages:

    models.py       Note / NoteSection / NoteCitation / Tag / NoteTag ORM (5 new tables)
    schemas.py      DTOs + list query enums
    validation.py   pure title/type/scope/tag validation + text metrics + outline derivation
    errors.py       transport-agnostic domain errors (incl. optimistic-concurrency conflict)
    repository.py   all SQL (owner+workspace scoped, soft-delete aware, batched sections/tags)
    engine.py       the ONLY bridge to the AI pipeline (retrieval→context→LLM), injected
    service.py      lifecycle + autosave + tags + conversions + the generation pipeline
    runner.py       background execution (threadpool prod runner + inline test runner)
    api.py          authenticated async routes under /workspaces/{id}/notes and /tags

Business logic never lives in API handlers; the API never issues SQL directly; the package never
imports faiss (the engine is injected) and NEVER implements its own retrieval/context.
"""
