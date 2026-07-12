"""Semantic Memory & Graph Retrieval (Phase 7, Module 2) — knowledge-centric retrieval.

Evolves Phase-1 retrieval: a query is resolved to canonical GRAPH entities, the Module-1 knowledge graph
is traversed into a semantic neighborhood, graph hits are scored on measurable graph signals, and fused
with vector/multimodal retrieval through the EXISTING Phase-4 fusion (graph = a new modality). It REUSES
Module-1 extraction (query recognition), the Module-1 graph store, and the Phase-4 fusion — no new
retrieval pipeline. Graph retrieval also becomes an agent tool (`graph_search`), preserving the single
PromptPackage → AnswerService pathway.

    interfaces.py    GraphHit / Neighborhood / MemoryQuery + Protocols
    recognition.py   QueryEntityRecognizer (query → graph seeds; reuses Module-1 EntityExtractor)
    traversal.py     TraversalEngine (BFS/DFS N-hop, weighted, cycle-protected, workspace-isolated)
    retrievers.py    8 graph retrievers (entity/neighbor/relationship/evidence/topic/concept/backlink/reference)
    scoring.py       MemoryScorer (explainable graph-signal scoring)
    fusion.py        hybrid_fuse — reuses Phase-4 fuse() with `graph` as a modality
    context.py       graph-aware context assembly (dedup + rank + citations)
    cache.py         NeighborhoodCache (avoid repeated traversals)
    service.py       SemanticMemoryService + MemorySynchronizer
    models/repository/schemas/api  SemanticMemoryLog + coordination + DTOs + routes
"""
