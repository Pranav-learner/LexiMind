"""Temporal Intelligence — canonical persistence for chapters, topics & timeline events.

Introduced in Phase 5 Module 3 as FOUNDATIONAL PERSISTENCE ONLY: the production-ready
`Chapter`/`Topic`/`TimelineEvent` entities, repository, indexes, and API that Module-3 temporal
retrieval reads over. Initial values come from lightweight derivation (`derivation.py`) over Module-1
transcript/speaker/scene data. The full Temporal Intelligence Engine (Phase 5 Module 2) will later
ENRICH these canonical rows in place — this schema is the stable storage layer for the project.

    models.py       Chapter / Topic / TimelineEvent (canonical, indexed, versioned via `source`)
    derivation.py   pure lightweight heuristics (scene-aligned chapters, keyword topics, merged events)
    repository.py   all SQL for the canonical tables + workspace-scoped reads for retrieval
    service.py      ensure_derived (count-guarded) + derive (idempotent) + queries
    api.py          /workspaces/{id}/media/{doc}/chapters|topics|events + /temporal-intelligence/derive
"""
