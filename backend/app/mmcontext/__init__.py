"""Multimodal context domain (Phase 4, Module 4: Multimodal Context Engineering Engine).

The evolution of Phase-2 (`app/context/`), which stays UNTOUCHED. Where Phase-2 assembled text
chunks into an LLM context, this engine assembles evidence from EVERY modality (text, OCR, images,
diagrams, charts, tables, metadata) — retrieved by Module 3 — into one coherent, budgeted, cited,
explainable multimodal prompt.

    models.py       ContextBuildLog ORM (1 table — observability / Phase-9)
    schemas.py      MMEvidence / ContextBlock + API DTOs
    dedup.py        cross-modal duplicate detection (merge duplicates, keep complementary evidence)
    ranking.py      cross-modal evidence ranking (weighted, explainable signals)
    budget.py       adaptive token budget manager (allocate by query intent; hard ceiling)
    compression.py  multimodal compression (caption/OCR/table/metadata; citation-preserving)
    assembly.py     adaptive context assembly (intent-driven block ordering)
    prompt.py       the deterministic, inspectable multimodal prompt builder
    citations.py    cross-modal citation manager (every modality stays traceable)
    repository.py   ContextBuildLog writes + observability aggregation
    service.py      the orchestrator — CONSUMES Module-3 retrieval, runs the pipeline
    api.py          authenticated routes under /workspaces/{id}/context

Reuses Phase-2's tokenizer + Module-3's intent/retrieval; imports with no faiss/torch (the text
retriever is injected). Phase-1/Phase-2 behaviour is never changed.
"""
