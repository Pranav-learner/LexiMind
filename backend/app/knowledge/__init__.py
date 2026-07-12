"""Knowledge Extraction & Graph Construction (Phase 7, Module 1) — the semantic layer.

Turns LexiMind from document-centric to knowledge-centric: a background stage AFTER ingestion reads the
text every pipeline already produced (documents/OCR/tables/images via MultimodalChunk, audio/video via
media chunks + transcripts) and extracts a workspace-scoped Semantic Knowledge Graph — canonical
entities + typed relationships with provenance. It REUSES existing processing outputs (no re-processing)
and is storage-agnostic behind a `GraphStore` interface. This module BUILDS + MAINTAINS the graph;
graph retrieval/reasoning is Module 2+.

    validation.py    entity/relationship vocabularies + normalization
    gazetteer.py     curated known-entity KB + relationship cue patterns
    extraction.py    EntityExtractor + RelationshipExtractor (deterministic; injectable engine seam)
    resolution.py    GraphResolver (canonicalization + dedup index)
    validator.py     GraphValidator (integrity report)
    sources.py       cross-modal text collectors (reuse ingestion/media chunk tables)
    storage.py       GraphStore Protocol (Neo4j/AGE/Postgres-agnostic)
    repository.py    GraphRepository (SQL implementation of GraphStore)
    builder.py       GraphBuilder (extract → resolve → dedup → version → store → validate; incremental)
    events.py        GraphEventPublisher seam
    models/service/runner/schemas/api  tables + coordination + background runner + DTOs + routes
"""
