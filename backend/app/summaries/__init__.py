"""Summary domain module (Phase 3, Module 5: AI Summaries Engine).

Grounded, persistent summaries of a document / selection / workspace. Layered like the other
domain packages:

    models.py       Summary / SummarySection / SummaryCitation ORM (3 new tables)
    schemas.py      DTOs + list query enums
    validation.py   pure title/type/scope validation
    errors.py       transport-agnostic domain errors
    repository.py   all SQL (owner+workspace scoped, soft-delete aware, batched citations)
    engine.py       the ONLY bridge to the AI pipeline (retrieval→context→LLM per section), injected
    service.py      lifecycle + the generation pipeline (persist sections/citations, progress, cancel)
    runner.py       background execution (threadpool prod runner + inline test runner)
    api.py          authenticated async routes under /workspaces/{id}/summaries

Business logic never lives in API handlers; the API never issues SQL directly; the package never
imports faiss (the engine is injected) and NEVER implements its own retrieval/context.
"""
