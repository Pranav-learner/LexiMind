"""Temporal Retrieval & Context Engine (Phase 5, Module 3).

The evolution of the Phase-1 Retrieval Engine and Phase-2 Context Engine for TIME-based media. It
retrieves by time / speaker / topic / chapter / event / scene / frame / timestamp, fuses + reranks
those temporal signals, assembles a timeline-aware context, and builds an adaptive,
timestamp-preserving prompt with temporal citations — WITHOUT modifying Phase-1/2/4 behaviour (it
reuses their normalizer, tokenizer, and compressor). Exposed as an INSPECTABLE service (no live LLM),
matching the mmcontext precedent.

    models.py       TemporalSearchLog (observability)
    schemas.py      TemporalHit (timestamp/speaker/scene-preserving) + API contracts
    intent.py       temporal query analyzer (+ timestamp/relative-order parsing)
    retrievers.py   9 temporal retrievers behind one TemporalRetriever protocol
    fusion.py       generalized weighted fusion + temporal adjacency
    rerank.py       temporal reranker (modality/speaker/time-proximity priors; lazy cross-encoder)
    context.py      timeline-aware context (temporal dedup + timestamp-preserving compression)
    prompt.py       adaptive, timestamp-preserving prompt builder
    citations.py    temporal citations (timestamp/speaker/scene/frame)
    repository.py   workspace-scoped reads over media + tintel + search log
    service.py      the orchestrator (ensure-derived → analyze → retrieve → fuse → rerank → context → prompt)
    api.py          /workspaces/{id}/temporal/search (+ timeline/speakers/chapters/scenes/events/prompt/explain/stats/health)
"""
