"""Vision Intelligence domain (Phase 4, Module 2: Vision Intelligence Engine).

Where Module 1 EXTRACTED images, this module UNDERSTANDS them: classification, semantic captions,
structured diagram/chart/table/screenshot understanding, semantic metadata, and vision embeddings —
turning raw visual assets into first-class knowledge alongside text.

    models.py       3 tables: VisionJob / VisionAnalysis / VisionEmbedding
    validation.py   the image-classification taxonomy + kind mapping
    analyzers.py    pure structured-understanding builders (diagram/chart/table/screenshot) + captions
    engines.py      the ONLY bridge to CLIP/SigLIP/BLIP — injected, lazy (Fake + Pipeline + embedder abstraction)
    repository.py   all SQL for the vision tables
    service.py      the async pipeline (analyze → caption → structure → embed), caption write-back,
                    MultimodalChunk enrichment
    runner.py       background execution (threadpool prod runner + inline test runner)
    api.py          authenticated routes under /workspaces/{id}/documents/{doc}/vision (+ analyses/search)

Reuses Module 1 (IngestionRepository asset reads + AssetStorage). Nothing enters the FAISS text index
— vision knowledge lands on the Module-1 asset rows + MultimodalChunks (still `pending`), exposing the
interfaces future multimodal retrieval will consume. The package imports with no CLIP/torch.
"""
