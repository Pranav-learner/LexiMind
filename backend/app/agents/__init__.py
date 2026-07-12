"""Agent Framework & Tool Calling (Phase 6, Module 1) — the Agentic AI core of LexiMind.

The new orchestration layer ABOVE Retrieval + Context: a request flows through an interface-driven
runtime that plans, selects + executes tools (each a thin wrapper over an existing service), collects
evidence into memory, builds a structured PromptPackage, and hands it to the SINGLE answer pathway
(`answer_service.complete`). It creates NO second retrieval/context/LLM pipeline — it composes the ones
Phases 1–5 already built. This module is the framework every future agent (research/writing/verification/
multi-agent) plugs into without an architectural rewrite.

    interfaces.py      Protocols + value objects (Tool/ToolSpec/ToolResult/Planner/PermissionPolicy/…)
    context.py         AgentContext (scope + injected deps) + AgentState
    memory.py          MemoryManager (working/execution/scratchpad — no long-term semantic memory yet)
    permissions.py     PermissionManager (allowed tools + scoped grants; runtime never runs a denied tool)
    graph.py           serializable ExecutionGraph/GraphNode/ExecutionPlan (seq/parallel/conditional/retry/branch)
    registry.py        ToolRegistry (lazy) + AgentRegistry (descriptors; future agents declared, not built)
    tools/             concrete tools — thin wrappers over existing retrieval/generation/analytics services
    retry.py           bounded retry policy
    executor.py        ToolExecutor (validate→permit→execute→retry→timeout→structured; layered, async-ready)
    planner.py         HeuristicPlanner (lightweight, replaceable via the Planner protocol)
    prompt_package.py  PromptPackage → the single AnswerService inference pathway
    events.py          EventBus/sink (observability + future streaming)
    runtime.py         AgentRuntime — the central orchestrator (owns no per-tool business logic)
    models.py          AgentExecutionLog (telemetry only)
    repository/service/schemas/api  data access + coordination + DTOs + /workspaces/{id}/agent/* routes
"""
