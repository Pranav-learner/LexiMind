"""Multimodal Workspace domain (Phase 4, Module 5: Multimodal AI Workspace).

The capstone of Phase 4 — it UNIFIES every capability from Phases 1–4 into one seamless product
surface. It owns NO business logic and NO new tables; it is a COORDINATION layer:

    schemas.py   the unified surfaces (ingest / assets / timeline / pipeline / actions / overview)
    errors.py    transport-agnostic domain errors
    service.py   the WorkspaceOrchestrator — aggregates every domain's data + routes AI actions
    api.py       authenticated routes under /workspaces/{id}/ai

- `POST /ai/ingest` — "upload anything → automatic processing": reuses the document upload flow, then
  auto-enqueues Module-1 multimodal processing + Module-2 vision (the user never picks a pipeline).
- `GET /ai/assets` — the unified asset explorer (documents, images, diagrams, tables, figures,
  summaries, notes, decks, conversations).
- `GET /ai/timeline` — the workspace activity timeline.
- `GET /ai/pipeline-status/{doc}` — one view of a document's full pipeline (text + processing + vision).
- `POST /ai/action` — routes multimodal AI actions (summary/notes/flashcards, modality-focused) to the
  existing generation services.
- `GET /ai/overview` — workspace-wide multimodal statistics + observability.

Every dependency (index context, ingestor, and the ingestion/vision/summary/note/flashcard runners) is
INJECTED so the whole flow is testable inline; the orchestrator reuses the real services and runners
in production. Nothing here duplicates a pipeline or changes any prior module's behaviour.
"""
