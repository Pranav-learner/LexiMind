"""Multimodal ingestion domain (Phase 4, Module 1: Multimodal Document Processing Engine).

The ingestion engine for every FUTURE multimodal capability. It turns any uploaded file (native /
scanned / mixed PDF, image, screenshot, photo) into structured multimodal knowledge — classification,
OCR (cached), extracted images/tables/figures, unified multimodal chunks, and rich metadata —
WITHOUT touching the Phase-1 text retrieval pipeline (multimodal chunks land in a future embedding
queue with `embedding_status="pending"`).

    models.py       7 tables: ProcessingJob / OcrResult / ExtractedImage / ExtractedTable /
                    ExtractedFigure / MultimodalChunk / ProcessingLog
    validation.py   supported-format registry + validators (easy-to-extend)
    storage.py      the on-disk asset hierarchy (swappable for object storage)
    chunking.py     pure multimodal chunk builder (lightweight; the semantic text chunker is untouched)
    engines.py      the ONLY bridge to OCR/vision/PDF libs — injected, lazy (Fake + Pipeline impls)
    repository.py   all SQL for the ingestion tables
    service.py      the staged async pipeline (validate→classify→ocr→extract→chunk→metadata→queue)
    runner.py       background execution (threadpool prod runner + inline test runner)
    api.py          authenticated routes under /workspaces/{id}/documents/{doc}/process (+ status/assets)

Business logic never lives in API handlers; the API never issues SQL directly; the package never
imports OCR/vision libraries (the engine is injected) and NEVER modifies Phase-1/2 behaviour.
"""
