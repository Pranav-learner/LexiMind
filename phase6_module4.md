# Phase 6 — Module 4: Multi-Agent Orchestration Platform

> **Status:** ✅ Complete (Phase 6 capstone) · Backend `app/orchestration/` · Frontend `OrchestrationDashboard` · 24 new tests. The orchestrator composes Modules 1–3 — it makes N per-agent calls (each already funnelled through AnswerService) plus exactly ONE final aggregation call through the single AnswerService pathway. No AI pipeline is duplicated.

---

## 1. Module Overview

Modules 1–3 built a single AI worker that can plan, act, write, and verify. Module 4 turns that worker
into a **coordinated team**: a user objective is decomposed into a **task graph**, governed, scheduled
across **multiple specialized agents** (research / writing / comparison / study / verification) that
share context, and their outputs are merged into **one** grounded deliverable.

**Single-agent vs multi-agent:**

| Single agent (Modules 1–3) | Multi-agent orchestration (this module) |
|---|---|
| One agent answers one task | A planner decomposes the objective into a dependency graph of agent tasks |
| Sequential, one perspective | Parallelizable layers; specialists collaborate (research → compare → write → verify) |
| Re-retrieves per task | Shared context forwards evidence (retrieval runs once) |
| No coordination/recovery | Scheduler with retry, timeout, fallback, optional tasks, graceful degradation |
| One output | Result Aggregator merges outputs/citations/verification → ONE final synthesis |
| Per-run telemetry | Orchestration-level telemetry (graph, order, parallelism, recovery, cost) |

This is the foundation for autonomous research, enterprise AI workflows, and future distributed agent
clusters.

---

## 2. Previous Architecture

Before this module a complex task ran as **one** specialized agent:

```
User → AgentTaskService.run_task → (research | writing | comparison | study) → verify → Result
```

Limitations: no decomposition (a "research these papers, compare them, and build a study guide" request
had to be one agent's job or several disconnected manual calls); no cross-agent evidence reuse; no
coordinated recovery; and no single merged deliverable or orchestration-level audit trail.

---

## 3. New Architecture

```
User
  ↓
Orchestrator
  ↓
Task Planner ──────────► TaskGraph (serializable DAG)         Governance validates BEFORE execution
  ↓
Agent Scheduler (layered; parallel/retry/timeout/fallback/recovery)
  ├─ research  ─┐
  ├─ comparison ┤─ each node → AgentTaskService.run_task  (reuses Retrieval→Context→PromptPackage→AnswerService→Verify)
  ├─ writing   ─┤            ↕ Shared Context Manager (evidence reuse — no re-retrieval)
  ├─ study     ─┘            ↕ Communication Bus (structured messages, no chain-of-thought)
  └─ verification
  ↓
Result Aggregator  → merge outputs/citations/verification → ONE PromptPackage → ONE AnswerService call
  ↓
Final Verification (Module-3 VerificationService)
  ↓
Final Response  +  OrchestrationExecutionLog
```

---

## 4. Multi-Agent Framework

- **Orchestrator** (`orchestrator.py`) — the conductor: plan → govern → schedule → aggregate → verify.
  Owns no agent logic; dispatches every node through the reused per-agent pathway.
- **Task Planner** (`planner.py`) — heuristic, LLM-free decomposition of an objective into a `TaskGraph`
  (research is the shared evidence base; comparison/study run in parallel; writing depends on the
  strongest upstream analysis; an optional verification node checks the leaves).
- **Agent Scheduler** (`scheduler.py`) — runs the graph in dependency **layers** (priority-ordered),
  with retry, per-node timeout, fallback agent, optional-task tolerance, dependency-failure cascade
  (skip, don't crash), and an opt-in parallel path (session-per-node).
- **Communication Bus** (`bus.py`) — ordered **structured** messages (task_request / result / status /
  error / shared_ref) — artifacts only, never chain-of-thought. This buffer is the timeline.
- **Shared Context Manager** (`shared_context.py`) — stores each node's result and forwards a node's
  dependency evidence into `params["evidence"]` so reuse-capable agents don't re-retrieve.
- **Result Aggregator** (`aggregator.py`) — merges + de-dupes evidence/citations, combines the per-agent
  verification reports, and makes **one** `answer_fn` call to synthesize the final narrative.
- **Failure Recovery** — folded into the scheduler (retry → fallback → optional-skip → graceful
  degradation); a failed branch never aborts the whole run.
- **Governance** (`governance.py`) — quotas (max nodes/depth/width), loop/recursion guards, allowed
  agents, and per-run permissions/allowed-tools carried down to every node.

---

## 5. Backend Architecture

```
app/orchestration/
  interfaces.py     TaskNode / TaskGraph / OrchestrationPlan / AgentMessage + Protocols
  planner.py        TaskPlanner (objective → TaskGraph)
  registry.py       declarative workflow templates
  governance.py     GovernancePolicy (validated before scheduling)
  bus.py            CommunicationBus
  shared_context.py SharedContextManager
  scheduler.py      AgentScheduler (+ failure recovery, _with_timeout)
  aggregator.py     ResultAggregator (ONE PromptPackage → ONE AnswerService call)
  orchestrator.py   Orchestrator
  models.py         OrchestrationExecutionLog (new table)
  repository.py     OrchestrationRepository
  service.py        OrchestrationService (run/plan/templates/history/retry/cancel/stats)
  schemas.py        DTOs
  errors.py         transport-agnostic errors (status_code)
  api.py            /workspaces/{id}/orchestration/*
```

- **Interfaces / DI** — planner, scheduler, aggregator are Protocols; the orchestrator dispatches nodes
  via `AgentTaskService.run_task` (Module 2) and verification via `VerificationService` (Module 3). The
  API reuses Module-1 `get_agent_services` — one injection surface (tests override it with a fake).
- **Caching / reuse** — shared-context evidence forwarding avoids duplicate retrieval; each node reuses
  the full Phase-1/2/4/5 pipeline; the aggregator reuses `PromptPackage` + `StructuredOutput`.
- **Validation / errors** — Pydantic request bounds; `GovernanceError` → 422, `OrchestrationNotFound` →
  404, `WorkflowNotFound` → 404, cancel-terminal → 409.
- **Error handling** — a node crash is captured as a failed node (data, not an exception); optional
  nodes degrade to skipped; the run returns `completed | partial | failed | cancelled`.

---

## 6. Frontend Architecture

- **`pages/OrchestrationDashboard.tsx`** (`/workspace/:id/orchestration`) — objective + template picker +
  live plan preview (the decomposed task graph); on run: a **layered workflow graph** (nodes colour-coded
  by status, showing dependencies / attempts / recovery / optional), an **execution timeline** (the
  communication-bus messages), **per-agent results**, the **unified output** (react-markdown), and the
  **final verification** (reuses the Module-3 `VerificationPanel`). A history sidebar reopens past runs.
- **`api/orchestration.ts`** — self-contained client + types + presentation helpers (status colours,
  agent icons). Client-side `layersOf()` mirrors `TaskGraph.layers()` for the graph view.
- **State / routing** — local React state; lazy route + a hub link (🕹️ Agent Orchestration).

---

## 7. AI Integration (no duplicate pipelines)

```
Orchestrator
  → (per node) AgentTaskService.run_task → Retrieval → Context → PromptPackage → AnswerService → Verify
  → Result Aggregator → ONE PromptPackage → AnswerService (final synthesis)
  → VerificationService (final trust pass)
```

- Every node runs the **existing** per-agent pathway — the orchestrator never re-implements retrieval,
  context engineering, prompt building, inference, or verification.
- **Single AnswerService pathway preserved:** all inference goes through `answer_fn` /
  `answer_service.complete`; the orchestrator adds exactly **one** final aggregation call (the "only one
  final PromptPackage → AnswerService" requirement) on top of the agents' own single-pathway calls.

---

## 8. Workflow Architecture

- **Task Graph** — serializable `TaskGraph` of `TaskNode`s (agent, objective, params, depends_on, mode,
  optional, priority, retries, timeout, fallback, forward_evidence) + runtime status.
- **Scheduling** — `layers()` topo-sorts into parallelizable groups; priority orders within a layer.
- **Dependencies** — a node runs only when all deps are OK/RECOVERED, else it is SKIPPED (cascade).
- **Parallelism** — layer width is reported; opt-in true-parallel execution (session-per-node) when a
  session factory is present; sequential-within-layer by default (SQLite session safety).
- **Communication** — structured bus messages drive the timeline + dashboard.
- **Recovery** — retry → fallback → optional-skip → graceful degradation.
- **Extensibility** — new agents/templates register with no scheduler change; a custom graph submitted
  over the API is just an unnamed template. The `run_node` seam is where a **distributed executor** drops
  in for Phase 7.

---

## 9. API Documentation

All routes under `/workspaces/{workspace_id}/orchestration`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/run` | Run a workflow (`objective`, optional `workflow` template or custom `graph`) → full result |
| POST | `/plan` | Decompose an objective into a task graph (no execution) |
| GET | `/templates` | List declarative workflow templates |
| GET | `` | Orchestration history |
| GET | `/stats` | Counts + avg latency |
| GET | `/{id}` | Run detail (graph + messages + node_results + output + final_verification) |
| GET | `/{id}/graph` | The task graph (with per-node status) |
| GET | `/{id}/timeline` | The communication-bus message timeline |
| POST | `/{id}/retry` | Re-run the workflow (new id) |
| POST | `/{id}/cancel` | Cancel (409 if already terminal) |

**Run response:** `{orchestration_id, objective, workflow, status, graph, agents_used, schedule{completed,
failed,skipped,recovered,retries,parallel_tasks}, timeline[], node_results[], output{markdown,…},
answer, citations[], combined_verification, final_verification, llm_calls, token_usage, cost_estimate,
timings{planner_ms,schedule_ms,aggregate_ms,total_ms}}`.

**Errors:** 422 governance violation (cycle / self-dep / unknown agent / quota), 404 workspace/run/
template, 409 cancel-terminal, 401/403 unauthenticated.

---

## 10. Performance Optimizations

- **Parallel execution** — independent nodes form a layer; opt-in threadpool (session-per-node) runs them
  concurrently; layer width is always reported.
- **Shared context reuse** — dependency evidence is forwarded so retrieval runs once per workflow.
- **Prompt/verification reuse** — reuses `PromptPackage`, `StructuredOutput`, and the Module-3 content-
  addressed verification cache; the aggregator makes exactly one synthesis call.
- **Large workflows** — governance caps node count/depth/width; the planner keeps graphs shallow and wide.
- **Scheduling** — `layers()` is O(V+E); priority ordering is a cheap sort.

---

## 11. Testing

- **`tests/test_orchestration_unit.py` (14)** — planner decomposition (compare+study parallelism, simple
  research→write), task graph (layers/priority/serialize), governance (cycle/self-dep/unknown-dep/unknown
  -agent/quota), communication bus (structured, ordered), shared context (evidence forwarding), scheduler
  (dependency order, skip-on-failed-dep, optional non-cascade, retry, fallback→recovered), aggregator
  (evidence merge/reindex, ONE answer call, worst-of verification), template validity.
- **`tests/test_orchestration_api.py` (10)** — plan-without-execute; full end-to-end run (graph executed,
  per-node **AgentTaskLogs written** via the reused pathway, unified output + final verification, persisted
  + detail + graph + timeline); named template; custom graph; governance rejections (cycle → 422, unknown
  agent → 422); templates list; stats + retry (new id) + cancel (409); auth; unknown template (404).
- **Regression** — new model `OrchestrationExecutionLog` registered in `init_db` + conftest; all Phase
  1–6 M3 tests continue to pass (full suite green).

---

## 12. File Changes Summary

**New (backend)** — `app/orchestration/{__init__,interfaces,planner,registry,governance,bus,
shared_context,scheduler,aggregator,orchestrator,models,repository,service,schemas,errors,api}.py`;
`tests/test_orchestration_unit.py`; `tests/test_orchestration_api.py`.

**Modified (backend)** — `app/db/base.py` (register `OrchestrationExecutionLog`), `app/main.py` (mount
router), `tests/conftest.py` (register model + mount router).

**New (frontend)** — `src/api/orchestration.ts`; `src/pages/OrchestrationDashboard.tsx`;
`src/styles/orchestration.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

*(No Module 1–3 source files were modified — Module 4 is purely additive, composing the existing
services, so there is zero regression surface in the prior modules.)*

---

## 13. Future Compatibility

- **Phase 7 — Knowledge Graph & Semantic Memory** — the task graph + shared context + verified claims are
  the substrate for a persistent knowledge/semantic-memory layer; the SharedContextManager is where a
  semantic-memory backend plugs in.
- **Enterprise AI / governance** — `GovernancePolicy` already models quotas/permissions; enterprise
  approval hooks (human-in-the-loop) drop in as a pre-node gate without scheduler changes.
- **Distributed agent clusters** — the `run_node` seam + serializable `TaskGraph` + structured message
  bus are exactly what a distributed/queue-backed executor needs; nothing above it changes.
- **External SaaS integrations** — new agents are new node types; new tools are new registry entries.
- **Real-time autonomous workflows** — the bus is streaming-ready (an SSE/websocket sink), and the
  confidence/verification signals are the control loop for "keep working until verified".

---

## 14. Lessons Learned

- **Compose, don't re-implement.** The whole platform reuses `AgentTaskService.run_task` (which already
  chains retrieval → context → PromptPackage → AnswerService → verification) as the per-node primitive, so
  the orchestrator is pure coordination — it added zero AI pipeline and touched no Module 1–3 source file.
- **One inference pathway, many calls.** "Single AnswerService pathway" means one code path, not one call:
  each agent makes its single-pathway call and the aggregator adds exactly one final synthesis call.
  Keeping that explicit (and LLM-free elsewhere — planning, governance, scheduling, merging) kept the
  platform testable without a model.
- **Layers make parallelism free and safe.** Modelling the graph as topological layers gave parallel
  structure, deterministic ordering, and a natural place for the SQLite-safe sequential default with an
  opt-in parallel path — mirroring the Module-1 executor.
- **Graceful degradation over hard failure.** Skipping the dependents of a failed required node (instead
  of aborting) plus optional-task tolerance means a partial-but-useful result beats an all-or-nothing crash.
- **Tradeoffs / limitations.** Execution is synchronous (cancellation is the terminal-409 seam, not mid-run
  interruption); true parallelism needs a session factory (SQLite session isn't thread-safe); node timeouts
  can't hard-kill a running DB op (best-effort, mirroring the Module-1 executor); decomposition is heuristic
  (an LLM planner drops in behind the `TaskPlanner` protocol). Resume-from-failure and streaming progress
  are the natural next steps (the bus + per-node AgentTaskLogs already make them tractable).
