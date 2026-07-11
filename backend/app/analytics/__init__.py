"""Analytics domain (Phase 3, Module 9: Knowledge Dashboard & Analytics Platform).

The executive dashboard of LexiMind. Like Modules 8, this package owns almost no primary data — it
AGGREGATES the other modules (documents, chat, summaries, notes, flashcards, citations, reading
sessions) into dashboard widgets, and caches each widget's payload so large workspaces load fast.

    models.py       AnalyticsSnapshot ORM (1 cache table)
    aggregators.py  the statistics/analytics engine — an extensible WIDGET REGISTRY (@widget)
    insights.py     the recommendation engine (deterministic, data-driven)
    schemas.py      visualization DTOs (the frontend contract)
    errors.py       transport-agnostic domain errors
    repository.py   the cache layer + the cheap COUNT-based signature (cache invalidation)
    service.py      caching orchestration (compute-or-cache, dashboard assembly, refresh)
    api.py          authenticated read routes under /workspaces/{id}/dashboard

Widgets are independently extensible: a future module adds a dashboard widget by decorating a
function with `@widget("key")` — no existing code changes. Nothing here mutates other modules or
alters the retrieval pipeline; it only consumes metrics already produced by Phases 1–2 and 3.
"""
