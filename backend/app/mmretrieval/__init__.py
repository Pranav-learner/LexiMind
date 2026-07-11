"""Multimodal retrieval domain (Phase 4, Module 3: Multimodal Retrieval Engine).

The evolution of Phase-1 retrieval into a UNIFIED multimodal search platform. Phase-1's
`app/retrieval/` (dense+BM25+RRF+reranker over FAISS) is UNTOUCHED — this module wraps it as the
`text` retriever and adds retrievers for OCR, images, diagrams, tables, and metadata over the stores
Modules 1–2 populated (`MultimodalChunk`, `VisionAnalysis`, `ExtractedTable`, `Document`).

    models.py       RetrievalLog ORM (1 table — search stats / Phase-9 dashboards)
    intent.py       query understanding — which modalities to activate (+ fusion weights)
    normalize.py    per-retriever score normalization → comparable [0,1]
    fusion.py       generalized weighted fusion (RRF / weighted-sum), cross-modal dedup
    retrievers.py   the common Retriever interface + text/ocr/image/diagram/table/metadata retrievers
    rerank.py       cross-modal reranking (modality-aware, model-swappable)
    repository.py   reads over the unified stores + RetrievalLog + stats
    service.py      the Retriever Orchestrator (intent→retrieve→normalize→fuse→rerank→explain→log)
    api.py          authenticated routes under /workspaces/{id}/search

Every retriever implements one interface (plug-and-play); every result carries a full retrieval
explanation (Step 8). The package imports with no faiss/torch (the production text retriever + the
cross-encoder reranker lazy-import Phase-1); Phase-1/Phase-2 behaviour is never changed —
`to_context_chunks` only EXPOSES the seam future multimodal Context Engineering will consume.
"""
