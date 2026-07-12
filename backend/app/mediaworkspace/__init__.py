"""Audio & Video AI Workspace (Phase 5, Module 4) — the product-integration capstone of Phase 5.

The temporal analogue of the Phase-4 `mmworkspace` orchestrator: it owns NO business logic and NO
retrieval/generation pipelines — it COORDINATES the existing domains into one seamless media
experience where documents, images, and recordings coexist. Users upload a lecture, ask a question,
and get a timestamp-aware answer with citations — never thinking about ASR / diarization / temporal
retrieval / context engineering / prompt building.

    engine.py       TemporalChatEngine — media chat that plugs into the EXISTING chat pipeline
                    (temporal retrieval → timestamp-preserving prompt → answer_service; the single LLM path)
    models.py       MediaInteractionEvent — the ONE observability table (Step 15 telemetry)
    repository.py   interaction-telemetry SQL (everything else reuses existing domain repos)
    service.py      MediaWorkspaceOrchestrator — overview / library / unified_timeline / playback /
                    media_chat (reuses ChatService.run_message) / ai_action (reuses summaries/notes/
                    flashcards) / unified search (temporal ⊕ multimodal) / observability
    api.py          /workspaces/{id}/media-ai/*  (thin transport; engine + runners injected)

Reuse, never duplicate: temporal intelligence flows through app.tretrieval / app.tintel / app.media;
answers through app.services.answer_service; knowledge assets through the existing generation services.
"""
