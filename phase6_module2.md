# Phase 6 — Module 2: Research & Writing Agents

> **Status:** ✅ Complete · Backend `app/agents/specialized/` + `app/agents/task_*.py` · Frontend `AgentWorkspace` · 30 new tests · full suite **567 passed, 0 failures**.

---

## 1. Module Overview

Module 1 gave LexiMind an **Agent framework**: an interface-driven runtime that plans, selects and
executes tools (thin wrappers over the existing retrieval/generation services), collects evidence into
a `PromptPackage`, and answers through the single `AnswerService` pathway. That runtime is a great
**one-shot** agent — it turns a question into a grounded answer.

Module 2 builds the first **autonomous, multi-step workers** on top of that framework. Where a chatbot
answers a message, an *AI employee* runs a **task**: it plans, researches across the whole workspace
(documents, images, recordings, timelines), ranks and de-duplicates evidence, notices what's missing,
and produces a **structured, citation-preserving deliverable** (a research report, a written document,
a comparison, a study pack). It can chain those steps into **workflows** (research → write → study).

Why specialized agents are necessary:

| Chatbot (Module 1 runtime) | Autonomous task agent (Module 2) |
|---|---|
| Single plan → single answer | Multi-phase: plan → research → analysis → write |
| One retrieval pass | Decomposes the objective, retrieves per sub-question, ranks + de-dupes |
| Answer text | Structured deliverable (headings/tables/lists/citations/references), exportable |
| No notion of "gaps" | Explicitly reports knowledge gaps |
| No reuse across steps | Evidence cache + workflow evidence hand-off (no repeated retrieval) |
| Stateless | Task memory (working/evidence/results/notes) + task telemetry log |

**The hard rule for this module:** reuse everything. No agent creates a second retrieval pipeline, a
second prompt builder, or a second inference path. Each specialized agent is *domain-specific planning
+ orchestration* that **delegates** retrieval → Phase 1/4/5, context → Phase 2/4, prompt building →
`PromptPackage`, and inference → the single `answer_service.complete`.

---

## 2. Previous Architecture (how complex tasks were handled before)

Before this module, a "complex" request went through the Module-1 runtime:

```
User → AgentRuntime → HeuristicPlanner → ToolExecutor (search/generate tools)
     → PromptPackage → answer_service.complete → Answer
```

Limitations for real work:

- **One retrieval pass, one answer.** "Research the trade-offs between X and Y across the lectures and
  write a report" collapsed into a single search + single answer — no decomposition, no cross-source
  ranking, no report structure.
- **No deliverable.** The output was a chat-style string; there was no structured, exportable artefact
  with a stable outline and a citations section.
- **No multi-step reuse.** Nothing carried evidence from a "research" step into a "write" step, so any
  multi-stage behaviour re-retrieved from scratch.
- **No task telemetry.** `AgentExecutionLog` records a single run's trace; there was no per-task record
  (phased timings, evidence/document/media counts, the produced deliverable) to power a history/export
  UX.

---

## 3. New Architecture

```
User
  ↓
Agent Runtime  (Module-1 framework: registry · executor · tools · prompt-package · single answer path)
  ↓
Specialized Agent  (research | writing | comparison | study)
  ↓
Planning     → decompose objective, select tools, build a phased plan
  ↓
Research     → run search tools through the framework executor → collect + rank Evidence
  ↓
Analysis     → identify knowledge gaps (no LLM)
  ↓
Writing      → build a PromptPackage → answer_service.complete   (SINGLE inference pathway)
  ↓
(Verification — Module 3, future)
  ↓
StructuredOutput  (headings/tables/lists/code/citations/references — Markdown now, DOCX/PDF/slides later)
  ↓
AgentTaskLog  (task telemetry + the persisted deliverable → history / preview / export)
```

The **Agent Runtime stays the orchestrator** — specialized agents call its executor, its tools, its
prompt package, its single answer function. They add *planning and shaping*, not new infrastructure.

---

## 4. Agent Architecture

All specialized agents implement one interface (`app/agents/specialized/base.py`):

```python
class SpecializedAgent(Protocol):
    name: str
    task_type: str
    def run(self, task: AgentTask, ctx: AgentContext, *, executor, events) -> AgentTaskResult: ...
```

`BaseSpecializedAgent` (ABC) supplies the reusable orchestration so every agent does things ONE way:

- `search_graph(tools, query, top_k)` — build a parallel `ExecutionGraph` of existing search tools.
- `gather(...)` — run that graph through the **Module-1 `ToolExecutor`** and reshape `ToolResult`s into
  ranked, de-duplicated `Evidence` (permission gating + retries + timeouts come free from the executor).
- `synthesize(system, instruction, evidence, …)` — assemble a `PromptPackage` and call
  **`ctx.answer_fn()`** (prod `answer_service.complete`, tests a fake). The runtime never calls the LLM
  directly.
- `count_media(...)` — reuse `DocumentRepository` to tell documents from recordings for scope decisions.

**Research Agent** (`research_agent.py`) — `plan` (decompose objective via `derive_subquestions`, pick
tools: `workspace_search` always, `temporal_search` when a recording is in scope or the objective has a
media cue) → `research` (gather per sub-question, rank, cache) → `analysis` (sub-questions with zero
evidence become knowledge gaps) → `write` (a grounded report). Supports workspace-wide, document,
topic, cross-document, cross-modal and timeline-aware research (tool selection + scope adapt).

**Writing Agent** (`writing_agent.py`) — 10 document types (technical/research report, study guide,
lecture notes, meeting minutes, design doc, architecture summary, documentation, executive summary,
plain Markdown), each with an outline + style system prompt. Reuses evidence handed down from a prior
workflow step (`params["evidence"]`) to avoid re-retrieval; otherwise gathers fresh. One
`answer_service` call produces the document.

**Comparison Agent** (`comparison_agent.py`) — resolves 2+ targets (explicit `targets`, ≥2 scoped
documents, or an "X vs Y" objective), gathers **per-target** evidence (scoping `ctx.document_id` per
target), then synthesizes **Similarities / Differences / Conflicts / Missing Information** with a
side-by-side target table. Multimodal because the underlying retrieval is multimodal.

**Study Agent** (`study_agent.py`) — reuses the **existing generation tools** (`generate_notes`,
`generate_flashcards`, `generate_summary`) which enqueue via the injected async runners, plus the
**Knowledge Dashboard** (`query_dashboard`) for weak topics, then synthesizes a learning plan.
Deliverables: notes, study_guide, flashcards, quiz, summary, revision, weak_topics, learning_path,
revision_plan, exam_prep. No business logic is duplicated — it orchestrates the Phase-3 services.

**Workflow Engine** (`workflows.py`) — serializable `WorkflowDefinition`/`WorkflowStep`; the engine
topologically orders steps, threads context, and forwards a step's evidence to dependents
(`forward_evidence`). Built-ins: `research_and_write`, `compare_and_summarize`, `study_pack`,
`research_write_study`. The `run_task` callback is the seam a future distributed/multi-agent executor
(Module 4) replaces.

**Memory** (`task_memory.py`) — `TaskMemory` extends the Module-1 `MemoryManager` with `evidence`
(the retrieval cache), `results` (intermediate phase outputs) and `agent_notes`. No long-term semantic
memory (that is Phase 7).

**Observability** (`AgentTaskLog`) — one task-scoped telemetry table (see §9/§12).

---

## 5. Backend Architecture

Layered per the project convention, inside the existing `app/agents/` domain:

```
app/agents/
  specialized/
    base.py            interface + AgentTask/Evidence/AgentTaskResult/PhaseTimings/AgentStep + BaseSpecializedAgent
    outputs.py         StructuredOutput + OutputBlock (Markdown renderer; DOCX/PDF/slides = future renderers)
    task_memory.py     TaskMemory (extends MemoryManager)
    research_agent.py  ResearchAgent
    writing_agent.py   WritingAgent (+ DOC_TYPES)
    comparison_agent.py ComparisonAgent
    study_agent.py     StudyAgent
    workflows.py       WorkflowDefinition/Step + WorkflowEngine + built-ins
    registry.py        task_type → agent implementation
  models.py            + AgentTaskLog                (new table; AgentExecutionLog untouched)
  task_repository.py   AgentTaskRepository           (AgentTaskLog data access only)
  task_service.py      AgentTaskService              (build ctx → dispatch → persist → history/retry/cancel/export/workflow/preview)
  task_schemas.py      Pydantic DTOs
  task_api.py          /workspaces/{id}/agent-tasks/*  (reuses Module-1 get_agent_services DI)
```

- **Repositories** — `AgentTaskRepository` owns only `AgentTaskLog` (owner+workspace scoped). Retrieval
  stays in the retrieval repos; generation stays in the Phase-3 repos — the agents call them via tools.
- **Services** — `AgentTaskService` builds the request-scoped `AgentContext` (+ `TaskMemory` +
  `InMemoryEventSink` + a `ToolExecutor` with a `PermissionManager`), dispatches to the specialized
  agent, and persists an `AgentTaskLog`. It contains **no** agent/retrieval logic.
- **Dependency injection** — the API reuses **`get_agent_services`** from Module 1 (the single answer
  function + the async generation runners). Tests override that one dependency with a fake answer +
  inline runners, exactly as for the Module-1 runtime — one injection surface for the whole platform.
- **Caching** — evidence is cached in `TaskMemory`; workflow steps forward evidence so downstream steps
  never re-retrieve; the reranker/retrieval caches from Phases 1/4/5 are reused unchanged.
- **Validation** — Pydantic request models (bounds on `top_k`/`evidence_limit`, a `task_type` pattern
  for preview); a comparison with < 2 targets returns a failed (not crashed) result.
- **Error handling** — transport-agnostic `AgentError` subclasses carry `status_code`; the API maps
  them (`ExecutionNotFound` → 404, `AgentStateError` → 409, unknown workflow → 404). A synthesis
  failure degrades to a `failed` result with an empty output, never a 500.

---

## 6. Frontend Architecture

- **Page** — `pages/AgentWorkspace.tsx` at `/workspace/:workspaceId/agents` (lazy-loaded, `RequireAuth`).
  Three-column layout: **configure** (agent picker · objective · scope · doc-type/deliverables ·
  workflow selector · live plan preview), **results** (title/summary · phase pipeline with per-step
  timings · tabs: output / evidence / plan / timeline / citations · export .md/.json · retry), and a
  **history** sidebar (click to reopen a task).
- **Progress UI / Execution timeline** — the phase pipeline renders each `AgentStep` (planning →
  research → analysis → writing) with its wall-clock; the *timeline* tab renders the event stream.
- **Evidence viewer** — the *evidence* tab lists ranked evidence with origin tool, timespan/page, score.
- **Live output** — the *output* tab renders the deliverable Markdown via `react-markdown` + `remark-gfm`
  (tables), matching the chat/summary renderers.
- **History / routing / state** — `listTasks` populates the sidebar; `getTask` reopens detail; local
  React state only (no store), consistent with the other feature pages. A debounced `previewTask` shows
  the plan as the user types (no execution).
- **API client** — `api/researchAgents.ts` (self-contained types + calls), built on the shared
  `apiRequest` wrapper. A link was added to the `WorkspaceDetail` hub (🧑‍🔬 Agent Workspace).

---

## 7. AI Integration (no duplicated pipelines)

Every agent reuses the shared stack — verified by the tools each phase calls:

```
Retrieval          workspace_search → app.mmretrieval (Phase 1 text + Phase 4 multimodal)
   ↓               temporal_search  → app.tretrieval  (Phase 5 time/speaker/chapter/…)
Context Eng.       (inside the retrieval services: Phase 2 dedup/rank/budget/compress + Phase 4 mmcontext)
   ↓
PromptPackage      app.agents.prompt_package.PromptPackage  (the ONE structured hand-off)
   ↓
AnswerService      ctx.answer_fn() → answer_service.complete (the ONE inference entry point)
   ↓
Citation Intel.    evidence carries the same citation dicts the rest of LexiMind uses
   ↓
Workspace          scope + counters + generation via the existing Summary/Notes/Flashcards services
```

- **No new retrieval logic** — agents build an `ExecutionGraph` of existing search tools and run the
  Module-1 executor.
- **No new prompt builder** — everything renders through `PromptPackage`.
- **No bypass of AnswerService** — synthesis always goes through `ctx.answer_fn()`.
- **Generation reuse** — the Study Agent enqueues Summary/Notes/Flashcard assets through the exact
  tools + injected runners the rest of the app uses (asserted in tests via the existing flashcards API).

---

## 8. Workflow Architecture

- **Definitions** — `WorkflowDefinition(name, description, steps=[WorkflowStep(...)])`, each step naming
  a `task_type`, `params`, `depends_on`, `forward_evidence`, optional per-step `objective`. Fully
  `to_dict`/`from_dict` serializable → persistable + API-supplied overrides (`definition_override`).
- **Execution** — `WorkflowEngine.run` topologically orders steps and runs them sequentially via the
  `run_task` callback (the service wires this to `AgentTaskService.run_task`, so **every step persists
  its own `AgentTaskLog` tagged with the workflow**).
- **Evidence hand-off** — `forward_evidence=True` feeds a dependency's evidence into the next step's
  `params["evidence"]` → the writing/summary step reuses retrieval instead of searching again.
- **Cancellation / resuming** — the engine checks a `cancel_flag` between steps; steps are independent
  `AgentTaskLog` rows, so a future resume can re-drive only the incomplete steps.
- **Future multi-agent** — the `run_task` seam is where Module 4 swaps sequential execution for
  distributed/collaborative execution without touching the definitions or the agents.

---

## 9. API Documentation

All routes under `/workspaces/{workspace_id}/agent-tasks`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/research` | Run the Research Agent → `TaskResult` |
| POST | `/writing` | Run the Writing Agent (`doc_type`) → `TaskResult` |
| POST | `/comparison` | Run the Comparison Agent (`targets`/`document_ids`) → `TaskResult` |
| POST | `/study` | Run the Study Agent (`deliverables`) → `TaskResult` |
| POST | `/workflows/{name}/run` | Run a workflow → `WorkflowRunResult` |
| POST | `/preview` | Plan preview (no execution, no LLM) |
| GET | `/agents` | Implemented specialized agents |
| GET | `/workflows` | Registered workflow definitions |
| GET | `` | Task history (`limit`, `task_type` filter) |
| GET | `/stats` | Task counts / avg latency / total tokens |
| GET | `/{task_id}` | Task detail (plan + steps + timeline + output) |
| GET | `/{task_id}/export?format=markdown\|json` | Export the deliverable |
| POST | `/{task_id}/retry` | Re-run the task (new `task_id`) |
| POST | `/{task_id}/cancel` | Cancel (409 if already terminal) |

**Request (research):** `{ objective, document_ids?, top_k?, evidence_limit?, granted_permissions?, allowed_tools? }`.
**Response (`TaskResult`):** `{ task_id, agent, task_type, objective, success, phase, error, plan, steps[],
evidence[], knowledge_gaps[], output{title,summary,markdown,blocks,citations,references}, citations[],
timings{planner_ms,research_ms,analysis_ms,writing_ms,total_ms}, tool_calls, documents_used, media_used,
workspace_used, token_usage, estimated_cost, timeline[] }`.

**Validation/errors:** Pydantic bounds (`top_k` 1–50, `evidence_limit` 1–100, preview `task_type`
pattern); 404 unknown workspace/task/workflow, 409 cancel-terminal, 401/403 unauthenticated.

---

## 10. Performance Optimizations

- **Avoid repeated retrieval** — evidence is cached per sub-question in `TaskMemory`; workflow steps
  forward evidence so a Research → Write chain retrieves once.
- **Reused caches** — the Phase-1/4/5 retrieval + rerank caches and the Phase-2/4 context engineering
  are reused unchanged; the Study Agent reuses the analytics compute-or-cache dashboard.
- **Incremental retrieval** — sub-question decomposition retrieves narrowly and ranks the union, rather
  than one broad query.
- **Streaming-ready** — every phase emits events to the `EventSink` (the timeline); an SSE sink drops in
  behind the same interface for live streaming, no agent change.
- **Partial results / resume** — cancellation returns a partial result; workflow steps are independent
  log rows, leaving room for step-level resume.
- **No unnecessary inference** — planning, gap analysis, and preview are heuristic (no LLM); only the
  writing phase calls the model, once.

---

## 11. Testing

- **`tests/test_research_agents_unit.py` (16)** — structured-output rendering (tables/citations/pipe
  escaping/empty-skip), workflow serialize + topo-order + cycle detection + evidence forwarding, task
  memory scopes + evidence cache, evidence de-dup/rank, `derive_subquestions`, and each agent's full
  phase machine driven by a fake executor + stub context (fake answer). Covers the "≥2 targets" guard,
  gap reporting, and "provided evidence ⇒ no retrieval".
- **`tests/test_research_agents_api.py` (14)** — the full pipeline over HTTP with the in-memory DB +
  fake answer + inline runners: run each agent, persist + list + detail + **export** (md & json), run a
  **workflow** (2 persisted steps), **preview** without persisting, **retry** (new id), **cancel**
  (409), stats, permission denial (generation tool denied ⇒ no asset), auth, unknown-workflow 404. The
  Study test asserts the created deck exists through the **existing** flashcards API.
- **Regression** — the two Module-1 registry assertions were updated (research_agent is now implemented;
  verification_agent remains the "planned" example). **Full suite: 567 passed, 0 failures.**

---

## 12. File Changes Summary

**New (backend)**
- `app/agents/specialized/{__init__,base,outputs,task_memory,research_agent,writing_agent,comparison_agent,study_agent,workflows,registry}.py` — the specialized-agent platform.
- `app/agents/task_repository.py` · `task_service.py` · `task_schemas.py` · `task_api.py` — data access, coordination, DTOs, routes.
- `tests/test_research_agents_unit.py` · `tests/test_research_agents_api.py` — 30 tests.

**Modified (backend)**
- `app/agents/models.py` — **+`AgentTaskLog`** (task telemetry + persisted deliverable; `AgentExecutionLog` untouched).
- `app/agents/registry.py` — research/writing/comparison/study descriptors flipped to `implemented`.
- `app/main.py` — mount `agent_tasks_router`.
- `tests/conftest.py` — mount `agent_tasks_router` on the test app (reuses the existing `get_agent_services` override).
- `tests/test_agents_unit.py` · `tests/test_agents_api.py` — registry assertions updated (see §11).

**New (frontend)**
- `src/api/researchAgents.ts` — API client + types.
- `src/pages/AgentWorkspace.tsx` — the Agent Workspace page.
- `src/styles/agentworkspace.css` — styles.

**Modified (frontend)**
- `src/App.tsx` — lazy import + `/workspace/:workspaceId/agents` route.
- `src/pages/WorkspaceDetail.tsx` — 🧑‍🔬 Agent Workspace hub link.

---

## 13. Future Compatibility

- **Module 3 — Verification & Reasoning** — the phase machine already has a labelled `writing` output +
  ranked evidence + citations; a `verification` phase slots between writing and finalization, re-using
  the same executor/tools to check claims against evidence. `verification_agent` stays a planned
  descriptor until then.
- **Module 4 — Multi-Agent Orchestration** — the `WorkflowEngine.run_task` seam is the single point a
  distributed/collaborative executor replaces; definitions are already serializable and agents already
  share one context/memory/permission model.
- **Knowledge Graph / Enterprise agents** — `Evidence`/`StructuredOutput` carry document + timeline +
  media references ready for entity/relationship extraction; `PermissionManager` already models
  scoped grants for RBAC.
- **External tools** — new capabilities are new `Tool`s in the registry; agents pick them up via
  `search_tools`/graph nodes with no runtime change.
- **Autonomous research** — the loop-friendly plan → research → gap-analysis structure is the base for a
  future "keep researching until gaps close" controller.

---

## 14. Lessons Learned

- **Reuse over re-architecture.** Making specialized agents *compose* the Module-1 executor + tools +
  prompt package + single answer function (rather than owning their own pipelines) kept the module small
  and guaranteed grounding/citation consistency with chat/QA. `BaseSpecializedAgent` is the only place
  orchestration lives.
- **The deliverable is data, not a string.** Modelling output as `StructuredOutput` (typed blocks +
  citations + references) made Markdown rendering, JSON export, history preview and future DOCX/PDF
  renderers fall out for free — and let the task log persist the product for re-open/export.
- **One injection surface.** Reusing `get_agent_services` meant the whole platform (Module 1 + 2) has a
  single place to swap the LLM + runners, so tests stayed fast (no ollama/faiss/torch) and honest.
- **Tradeoffs / known limitations.** Execution is **synchronous** (like Module 1) — cancellation is the
  terminal-409 seam, not true mid-run interruption; sub-question decomposition and gap analysis are
  **heuristic** (no LLM) by design, to avoid extra inference — an LLM planner can replace them behind the
  same call sites. Comparison scopes per target by temporarily setting `ctx.document_id` (fine for the
  synchronous, sequential executor). Evidence quality in tests is bounded by the faiss-free lexical
  retriever, so API tests assert structure + success rather than retrieval recall.
- **Future improvements.** Streaming output over SSE (sink already emits events), step-level workflow
  resume, DOCX/PDF/slide renderers over `StructuredOutput`, and an LLM-reasoning planner behind the
  `Planner` protocol.
