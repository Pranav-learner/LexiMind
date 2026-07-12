"""Interactive Knowledge Workspace (Phase 7, Module 4) — the Phase-7 capstone.

Turns Modules 1–3 (extraction · semantic memory · reasoning) into a knowledge-centric workspace: an
interactive graph explorer (lazy neighborhood loading), entity + relationship inspection, unified
knowledge search, an AI Graph Chat, a knowledge timeline, graph analytics, and controlled human-in-the-
loop editing. It is a PURE orchestrator (like the Phase-4/5 workspace capstones): it delegates to the
Module-1 graph store, Module-2 SemanticMemoryService, Module-3 GraphReasoningService, and the UNCHANGED
ChatService → single AnswerService pathway. No graph/retrieval/reasoning/inference logic is duplicated.

    models.py     KnowledgeWorkspaceLog (activity telemetry)
    editing.py    GraphEditor (rename/merge/split/delete/create/approve — versioned, soft-delete)
    engine.py     GraphChatEngine (chat-engine interface; graph retrieval + reasoning → answer_fn)
    analytics.py  graph analytics (read-only aggregation)
    timeline.py   knowledge timeline (read-only aggregation)
    service.py    KnowledgeWorkspaceOrchestrator
    repository/schemas/api  activity log + DTOs + /workspaces/{id}/knowledge-workspace/* routes
"""
