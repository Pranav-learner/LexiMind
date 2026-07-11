"""Citation-intelligence domain (Phase 3, Module 8: Citation Intelligence & Knowledge Explorer).

Turns every citation across LexiMind into an interactive, explainable, navigable knowledge node.
Unlike the other domains, this package owns NO primary data — it builds a DERIVED INDEX over the
citations that Modules 4–7 already persist (chat/summary/note/flashcard), so an answer's evidence
becomes fully traceable and every chunk becomes a backlink hub (Obsidian-style).

Layered like the other domain packages:

    models.py       Citation / CitationReference / KnowledgeReference ORM (3 derived-index tables)
    indexer.py      the ONLY reader of the 4 source citation tables → rebuilds the index (idempotent)
    schemas.py      DTOs + query enums
    validation.py   (light) — most inputs are query params
    errors.py       transport-agnostic domain errors
    repository.py   all reads over the index (search, references, knowledge, stats)
    explain.py      deterministic "why was this cited?" composer (pure)
    service.py      transparent sync + panel/explorer/explain/search/stats orchestration
    api.py          authenticated read routes under /workspaces/{id}/citations

The index is refreshed transparently on read (a cheap count-based staleness check). Nothing here
changes retrieval behaviour — it only EXPOSES metadata already collected by Phases 1–2.
"""
