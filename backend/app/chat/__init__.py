"""Chat domain module (Phase 3, Module 4: Persistent AI Chat Workspace).

Long-lived, workspace-scoped conversations grounded in the user's knowledge base. Layered like
the other domain packages:

    models.py       Conversation / Message / MessageCitation ORM (3 new tables)
    schemas.py      Pydantic DTOs + list query enums
    validation.py   pure title/description/message validation + auto-title
    errors.py       transport-agnostic domain errors
    repository.py   all SQL (owner+workspace scoped, soft-delete aware, batched citation reads)
    memory.py       token-aware conversation-history selection (reuses Phase-2 token estimate)
    engine.py       the ONLY bridge to the AI pipeline (retrieval→context→LLM), injected
    service.py      conversation lifecycle + the single message pipeline (stream + non-stream)
    api.py          authenticated routes under /workspaces/{id}/conversations

Business logic never lives in API handlers; the API never issues SQL directly; the chat package
never imports faiss (the AI engine is injected) and NEVER implements its own retrieval/context.
"""
