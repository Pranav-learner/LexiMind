# Phase 6 · Module 1 — Agent Framework & Tool Calling

> The biggest architectural shift in LexiMind. Everything before was an intelligent knowledge *system*;
> this module makes it an **agentic AI operating system**: an interface-driven **Agent Runtime** that
> plans, selects and executes tools, gathers evidence, and answers — a new orchestration layer *above*
> Retrieval and Context. It creates **no** second retrieval/context/LLM pipeline; it composes the ones
> Phases 1–5 already built, and preserves the **single `AnswerService` inference pathway**. This is the
> framework every future agent (research, writing, verification, multi-agent) plugs into.

---

## 1. Module Overview

**Why agentic AI differs from RAG.** Classic RAG is a fixed pipeline: `retrieve → context → LLM →
answer`. It cannot decide *whether* to retrieve, *which* source to use, *which action* to take
(generate a deck vs. search a lecture), run steps in parallel, recover from a failed step, or explain
its plan. An **agent** interprets intent, forms a plan, selects **tools**, executes them under
**permissions**, collects results into **memory**, and only then synthesizes an answer — observably and
recoverably.

**Why an Agent Runtime is necessary.** LexiMind already has many "tool-like" services (multimodal
search, temporal search, summaries, notes, flashcards, dashboard). Without a runtime, wiring them
together means bespoke glue per feature. The runtime is the *one* place that composes them —
consistently, with observability, permissions, and a single inference path — so new capabilities are
new **tools/agents**, not new pipelines.

**Overall architecture.** A new `app/agents/` package built entirely against small Protocols
(`Tool`, `Planner`, `PermissionPolicy`, `MemoryStore`, `EventSink`). The runtime depends only on these
abstractions; concrete tools are thin wrappers over existing services and add no business logic.

---

## 2. Previous Architecture

Before this module a request was a straight line:

```
User → Chat/QA → Retrieval → Context → LLM → Answer
```

**Limitations:** no planning (retrieval always ran, even for "hi" or "make flashcards"); no tool
selection (each feature hard-coded its own service calls); no multi-step/parallel/conditional
execution; no permission gate; no unified execution telemetry; no way to add a capability without
threading it through a specific feature. Generation, search, and analytics were reachable only through
their own endpoints, never *composed* by a reasoning layer.

---

## 3. New Architecture

```
                         User request
                              │
                        Agent Runtime            (owns no per-tool business logic)
                              │
                          Planner                (heuristic now; replaceable via Planner protocol)
                              │  → ExecutionGraph (serializable: seq / parallel / conditional / retry / branch)
                     Permission gate             (runtime never runs a denied tool)
                              │
                       Tool Executor             (validate → permit → execute → retry → timeout → structured)
             ┌────────────────┼────────────────┬───────────────┬─────────────┐
        workspace_search  temporal_search   generate_*     query_dashboard  retrieve_transcript   (tools = thin wrappers)
             └── reuse Phase-1/4 retrieval ── reuse Phase-5 temporal ── reuse existing generation/analytics ──┘
                              │
                     Agent Memory (working / execution / scratchpad)
                              │
                        PromptPackage            (structured, inspectable)
                              │
                  answer_service.complete()      ← THE single LLM pathway (injected, faked in tests)
                              │
                    Answer + AgentExecutionLog   (telemetry only)
```

**Key move:** the runtime is the new orchestration layer, but every arrow into a phase is a *reused*
service, and the only arrow to the LLM is `AnswerService`.

---

## 4. Agent Framework

| Piece | Responsibility |
|---|---|
| **Runtime** (`runtime.py`) | Compose the flow: plan → execute → collect → PromptPackage → answer → telemetry. No tool logic. |
| **Planner** (`planner.py`) | Heuristic intent → `ExecutionGraph` + cost estimate. Reuses existing intent analyzers; replaceable. |
| **Registry** (`registry.py`) | `ToolRegistry` (lazy tool instances) + `AgentRegistry` (descriptors; future agents declared, not built). |
| **Execution Graph** (`graph.py`) | Serializable DAG; dependency **layers**; sequential/parallel/conditional/retry/failure-branch/cancel. |
| **Memory** (`memory.py`) | `MemoryManager` — working/execution/scratchpad + conversation/workspace views. No long-term semantic memory (Phase 7). |
| **Permissions** (`permissions.py`) | Granted permission set + allowed-tools; `allows(spec, ctx)`; the runtime never runs a denied tool. |
| **Retry** (`retry.py`) | Bounded per-node retry of transient failures (permission denials are terminal). |
| **Observability** (`events.py` + `models.py`) | Event timeline + `AgentExecutionLog` (telemetry only). |

---

## 5. Backend Architecture

- **Interfaces first** (`interfaces.py`): `Tool`/`ToolSpec`/`ToolResult`, `Planner`, `PermissionPolicy`,
  `MemoryStore`, `EventSink` — structural Protocols, so nothing inherits and everything is swappable.
- **Dependency injection**: the runtime receives planner/executor/registry; `AgentContext.services`
  carries the *external* deps (`answer_fn`, the async generation runners, an optional `session_factory`
  for the parallel path) — so **tools never import FastAPI/runners/answer_service**. Tests inject a faked
  answer + inline runners; prod injects the real ones. Single seam (`get_agent_services`).
- **Repositories/services**: `AgentRepository` (only `AgentExecutionLog`); `AgentService` coordinates a
  run + persistence + discovery/history/retry/cancel. All other data access reuses existing domain repos.
- **Caching / avoid inference**: the planner never calls the LLM; small-talk and generation intents skip
  retrieval; the runtime makes exactly **one** LLM call per run. Tool results are memoized in execution
  memory within a run.
- **Validation / errors**: transport-agnostic errors carry `status_code` (404 tool/agent/execution,
  403 permission, 422 validation, 409 state, 504 timeout). A failing tool degrades to `ok=False` data —
  it never crashes the run.

---

## 6. Frontend Architecture

- **`pages/AgentDebugPanel.tsx`** (`/workspace/:id/agent`) — a developer panel: a request box with a
  **live plan preview** (debounced `/plan`, no execution), then tabs for **Answer / Graph / Tools /
  Timeline / PromptPackage**, plus sidebars for registered agents, tools, and recent executions.
- **Execution Graph** — nodes colored by status (ok/failed/denied/skipped), with dependencies + timing.
- **Tool Timeline** — the event stream (`plan → tool_start → tool_end → done`) with per-event ms.
- **Planner View** — rationale + intents + estimated cost, shown before running.
- **Execution History** — recent runs from `AgentExecutionLog`, one click to inspect.
- **State management** — plain React state + `AbortController`; debounced plan preview; no new dependency.
- **Routing** — lazy route + "🤖 Agent Runtime" CTA on `WorkspaceDetail`. `api/agents.ts` self-contained.

---

## 7. AI Integration

The runtime reuses, never forks:

```
Retrieval (Phase 1) ─┐
Multimodal (Phase 4) ─┤─► tools ─► evidence ─► PromptPackage ─► answer_service.complete()
Temporal (Phase 5)  ─┘                                            (the ONE inference pathway)
Summaries/Notes/Flashcards/Analytics ─► generation & analytics tools (existing services + runners)
```

There is exactly **one** path to the LLM: `PromptPackage.render()` → `answer_service.complete()`
(injected via `AgentContext.answer_fn()`). No tool and no runtime branch calls a model directly.

---

## 8. Tool Architecture

- **Interface**: a tool is any object with a `spec: ToolSpec` and `execute(ctx, args) -> ToolResult`.
  `ToolSpec` declares name/version/params/permissions/category/parallel_safe/timeout/cost — enough for
  discovery, validation, permission checks, and planning **without executing** the tool.
- **Registry**: lazy — tools are imported + registered on first use, so importing the framework pulls in
  no heavy service. Discovery/metadata/versioning read specs only.
- **Execution**: the executor validates → permission-checks → runs (retry + timeout) → captures a
  uniform `ToolResult` (structured `output` + `context_text` for the prompt + `citations` + telemetry).
- **Permissions**: each tool declares required permissions; a run grants a set; denied tools never run.
- **Lifecycle / extensibility**: adding a tool = a class + registry entry (no runtime change). The
  shipped set wraps: `workspace_search`, `temporal_search`, `unified_media_search`, `retrieve_transcript`,
  `query_dashboard`, `generate_summary`, `generate_notes`, `generate_flashcards`, `create_note`. Future
  tools (web/email/calendar/GitHub/Slack/filesystem) implement the same interface.

---

## 9. API Documentation

All routes authenticated (bearer) + workspace-scoped under `/workspaces/{ws}/agent`.

| Method | Path | Body/Query | Response | Errors |
|---|---|---|---|---|
| POST | `/run` | `{query, agent?, document_id?, conversation_id?, allowed_tools?, granted_permissions?}` | `RunAgentResponse` (answer + plan + tool_results + timeline + prompt_package + timings) | 404 |
| POST | `/plan` | `{query, document_id?}` | serialized `ExecutionPlan` (no execution) | 404 |
| GET | `/tools` · `/tools/{name}` | — | tool spec(s) | 404 (unknown tool) |
| GET | `/agents` | — | agent descriptors (implemented + planned) | 404 |
| GET | `/executions` | `?limit=` | recent `AgentExecutionLog`s | 404 |
| GET | `/executions/{id}` | — | full execution (graph + timeline) | 404 |
| GET | `/executions/{id}/graph` | — | serialized execution graph | 404 |
| GET | `/stats` | — | `{executions, successful, avg_total_ms}` | 404 |
| POST | `/executions/{id}/retry` | — | a NEW `RunAgentResponse` | 404 |
| POST | `/executions/{id}/cancel` | — | `ExecutionLogOut` | 404, 409 (terminal run) |

**`RunAgentResponse`** carries the full, inspectable execution: the plan + serialized graph (each node's
status/latency/attempts/error), per-tool structured results, the event timeline, the rendered
PromptPackage preview, timings (planner/tools/llm/total), retry count, token + cost estimates, and a
memory snapshot (keys only — no business data).

---

## 10. Performance Optimizations

- **Avoid unnecessary inference** — the planner is pure/heuristic (no LLM); small-talk → no tools;
  generation intents skip retrieval; exactly **one** LLM call per run.
- **Parallel structure** — the graph executes in dependency **layers** (parallel groups preserved +
  reported). Execution is sequential on the shared SQLite session (thread-safety), with an **async-ready**
  session-per-tool parallel path that activates when a `session_factory` is injected — so a future async
  executor needs no framework change.
- **Conditional pruning** — `has_results:<node>` conditions skip downstream tools when an upstream tool
  found nothing (no wasted work).
- **Bounded + timed** — every tool has a `timeout_s` guard and a bounded retry budget; a slow/broken tool
  degrades to data instead of hanging the run.
- **Reused retrieval/context** — tools call the existing engines, inheriting their caches (e.g. temporal
  `ensure_derived`, dashboard section caching); the framework adds no second cache.
- **Lazy registry** — tools import on first use; discovery reads specs without loading services.

---

## 11. Testing

Everything runs **offline** — a faked single-answer function (conftest overrides `get_agent_services`)
+ inline generation runners + the media `FakeMediaEngine`. No LLM/faiss/torch.

**Unit (`tests/test_agents_unit.py`, 16 tests):** planner routing (generation/QA/temporal-cue/greeting),
graph serialization + layering + cycle detection, tool & agent registries, and the executor with fake
tools — permission denial (never executed), transient-failure retry, conditional skip, and
abort-on-failure policy — plus permission manager, memory scopes, and PromptPackage rendering.

**Integration (`tests/test_agents_api.py`, 11 tests):** the full agentic loop over HTTP —
```
run → plan → tool selection → tool execution (real retrieval/generation services) →
PromptPackage → single answer pathway → AgentExecutionLog → history/graph/retry/cancel
```
including: tool/agent discovery; planner preview writes **no** log; a QA run selects `workspace_search`;
a media-scoped run adds `temporal_search`; a "make flashcards" run creates a real deck (visible via the
**existing** flashcards API); a permission-restricted run **denies** the generation tool; execution
logging + graph persistence; retry mints a new execution; cancel of a terminal run → 409; auth.

**Results:** 27 new tests pass. **Full suite: 527 passed** (500 prior + 27 new), `test_reranker`/
`test_eval` excluded per convention (torch). **Zero regressions** across Phases 1–5. Frontend `tsc -b`
clean; `vite build` succeeds (`AgentDebugPanel` chunk emitted).

---

## 12. File Changes Summary

### New — backend `app/agents/`
`__init__.py`, `interfaces.py`, `context.py`, `errors.py`, `memory.py`, `permissions.py`, `graph.py`,
`events.py`, `registry.py`, `retry.py`, `executor.py`, `planner.py`, `prompt_package.py`, `runtime.py`,
`models.py` (AgentExecutionLog), `repository.py`, `service.py`, `schemas.py`, `api.py`,
`tools/{base,search_tools,generation_tools}.py`.

### New — tests, frontend, docs
`tests/test_agents_unit.py`, `tests/test_agents_api.py`, `frontend/.../api/agents.ts`,
`frontend/.../pages/AgentDebugPanel.tsx`, `frontend/.../styles/agents.css`, `phase6_module1.md`.

### Modified (registration/wiring only — no behavior change)
| File | Change |
|---|---|
| `backend/app/db/base.py` | register `agents.models` in `init_db()` |
| `backend/app/main.py` | mount `agents_router` |
| `backend/tests/conftest.py` | register model + mount router + override `get_agent_services` (faked answer + inline runners) |
| `frontend/.../App.tsx` | lazy `/workspace/:id/agent` route |
| `frontend/.../pages/WorkspaceDetail.tsx` | "🤖 Agent Runtime" CTA |

No existing service was modified — retrieval, context, generation, and the answer service are **reused
unchanged**. No business logic was duplicated.

---

## 13. Future Compatibility

- **Phase 6 Module 2 (Research & Writing Agents)** — register a `research_agent`/`writing_agent`
  implementation (descriptors already declared) that drives the runtime with a multi-step plan; no
  framework change needed.
- **Phase 6 Module 3 (Verification & Reasoning)** — a smarter `Planner` (LLM reasoning) + a
  `verification` tool slot behind the existing Protocols; the graph already supports conditional/branch.
- **Phase 6 Module 4 (Multi-Agent Orchestration)** — the `AgentRegistry` + serializable `ExecutionGraph`
  are the substrate; an orchestrator agent composes sub-agent runs.
- **Knowledge Graph / Enterprise integrations / external tool ecosystem** — new tools implement the same
  `Tool` interface with their own permissions; the permission manager is the RBAC seam.
- **Async / streaming** — the event sink + layered executor + `session_factory` seam make a background
  runner + SSE a drop-in, no rewrite.

---

## 14. Lessons Learned

**Architecture decisions**
- *Interface-first, runtime owns no tool logic.* Keeping the runtime a pure composer (plan → execute →
  synthesize) and pushing all capability into `Tool` wrappers means new features never touch the core.
- *Tools are wrappers, not reimplementations.* Every tool delegates to an existing Phase-1/4/5 service,
  so there is genuinely one retrieval pipeline, one context pipeline, and — crucially — one LLM pathway.
- *Inject external deps through the context.* `AgentContext.services` (answer_fn + runners +
  session_factory) keeps tools free of FastAPI/runner imports and makes the whole runtime trivially
  testable with a faked LLM.
- *One telemetry table, serializable graph.* Persisting the plan/graph/timeline (telemetry only) on
  `AgentExecutionLog` gives history + the debug panel + future resumption without storing business data.

**Tradeoffs**
- The planner is deliberately heuristic (no LLM) — cheap and deterministic, but less flexible than
  reasoning-based planning (that is Module 2/3, and it drops in behind the `Planner` protocol).
- Execution within a layer is sequential (SQLite session thread-safety); true parallelism is the
  session-per-tool async-ready seam, not yet enabled by default.
- Cancellation is a state transition for the async future; synchronous runs are terminal on return.

**Known limitations & future improvements**
- No long-term/semantic agent memory yet (Phase 7) — only per-run working/execution/scratchpad.
- No LLM-driven tool-argument synthesis yet (tools default their args from the request/scope); a
  reasoning planner will fill richer args.
- Next: research/writing agents, an LLM planner, background+streaming execution, and an external-tool
  ecosystem — all additive on this framework.
