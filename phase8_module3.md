# Phase 8 — Module 3: AI Optimization & Cost Intelligence Platform

> **Status:** ✅ Complete · Backend `app/optimization/` · Frontend `OptimizationWorkspace` · 16 new tests. Turns LexiMind self-optimizing: an **Optimization Engine** runs as an automatic stage BEFORE execution — profiling the query, applying a per-workspace policy, routing to the cheapest model at acceptable quality, tuning retrieval/context/prompt parameters, and deciding cache-first — then applies the plan through the REAL pipeline and records estimated-vs-actual savings. It CONSUMES the Evaluation & Observability signals and TUNES the existing Retrieval / Context / PromptPackage / AnswerService / Verification systems; it never duplicates or bypasses them.

---

## 1. Module Overview

Until now LexiMind could **measure** quality (M1), **observe** every request (M2), and **benchmark** every pipeline. It ran one pipeline for every query — same retrieval params, same model path, no cache-first, no cost awareness. This module makes the platform answer, automatically: *which model is cheapest at acceptable quality? can this be served from cache? can context be compressed, graph traversal reduced, the reranker skipped? can we cut 60% of token cost without losing quality?*

**Observability vs optimization:**

| Observability (M2) | Optimization (this module) |
|---|---|
| *Reports* cost/latency/tokens after the fact | *Acts* on them before execution |
| "This request cost $X" | "Route to model Y, compress context, serve from cache → save Z%" |
| Passive, read-only telemetry | An active stage that shapes the pipeline |
| One fixed pipeline observed | Adaptive pipeline selected per query |

This is **automatic optimization, intelligent routing, adaptive pipelines, and cost-aware execution** — NOT feedback collection (that is Module 4).

---

## 2. Previous Architecture

```
Request  →  Pipeline (fixed retrieval + single answer path)  →  Answer
```

Every query, simple or complex, ran the same retrieval params (fixed top_k/hops), the same model path, and no answer cache. Cost was *observed* by M2 but never *acted on*. Limitations: no model routing, no adaptive retrieval/context, no prompt optimization, no cache-first serving, no cost-aware policy, no explainable savings.

---

## 3. New Architecture

```
Request
   ↓
Optimization Engine   ── profile query → resolve policy
   ↓
Pipeline Selection    ── adaptive by complexity (simple FAQ vs research)
   ↓
Model Routing         ── policy-weighted, provider-agnostic, context-fit
   ↓
Retrieval Optimizer   ── adaptive k / rerank / graph-hops / early-stop
   ↓
Context Optimizer     ── token budget / compression (citation-preserving)
   ↓
Prompt Optimizer      ── concise | standard | detailed template
   ↓
Cache decision        ── answer cache hit → short-circuit the whole pipeline
   ↓
Execution (REAL pipeline: retrieval → PromptPackage → AnswerService → Verification)
   ↓
Metrics + Observability + OptimizationRunLog (estimated vs actual, savings)
```

The engine produces one `OptimizationPlan`; execution applies it. Decision and execution are decoupled — a plan can be previewed without running anything.

---

## 4. Optimization Pipeline

- **Model Routing** (`router.py`) — scores every catalog model by normalized `weights·(cost, quality, latency)`, filtered by availability, offline flag, context-fit, and a quality floor from the request. Provider-agnostic — never hardcodes providers.
- **Retrieval Optimization** (`optimizers.py`) — adaptive top_k, rerank depth, hybrid dense/sparse weight, graph traversal depth, early-stopping, cache-first. Cost policies trim; quality policies widen.
- **Context Optimization** — dynamic token budget + compression (none/light/aggressive), redundancy removal, capped by the policy's max compression, **citations always preserved** (quality invariant).
- **Prompt Optimization** — template selection (concise/standard/detailed) + optional compression, reusing PromptPackage.
- **Caching** (`cache_intel.py`) — content-addressed answer cache (LRU + TTL) short-circuits repeated queries; aggregates the caches other modules already keep.
- **Policy Engine** (`policy.py`) — named objectives (lowest_cost / highest_quality / balanced / fastest / research / offline / developer / enterprise) → weight vectors, per-workspace.
- **Cost Intelligence** (`cost_intel.py`) — explainable recommendations with estimated savings.

---

## 5. Backend Architecture

```
app/optimization/
  interfaces.py    RequestProfile / ModelSpec / Retrieval|Context|PromptPlan / OptimizationPlan / Recommendation
                   + Optimizer / ModelProvider protocols (pluggable stages)
  catalog.py       ModelCatalog — provider-agnostic model specs (cost/quality/latency/context)
  policy.py        PolicyEngine — 8 named policies → normalized weights + flags
  profiler.py      QueryProfiler — deterministic complexity/tier/quality estimation
  router.py        ModelRouter — policy-weighted, context-fit selection + candidate scores
  optimizers.py    Retrieval / Context / Prompt optimizers (adaptive params)
  cache_intel.py   AnswerCache (LRU+TTL) + CacheIntelligence (aggregates all cache layers)
  cost_intel.py    CostIntelligence — explainable cost recommendations
  engine.py        OptimizationEngine — composes all of the above → one OptimizationPlan
  execute.py       apply_plan — runs the plan through the REAL retrieval→answer→verify pipeline
  models.py        OptimizationRunLog + WorkspacePolicy
  repository/service/schemas/api/errors  data access + orchestration + DTOs + routes
```

- **Interfaces / DI** — every stage optimizer implements the `Optimizer` protocol; the catalog is a `ModelProvider`. Future optimizers/providers plug in without touching the engine. The `run` endpoint reuses Module-1 `get_agent_services` (the single answer function).
- **Repositories / services** — `OptimizationRepository` (run logs + per-workspace policy); `OptimizationService` orchestrates preview/recommend/run/cost/policy/cache.
- **Validation / errors** — Pydantic policy-pattern (422 on bad policy); `UnknownPolicy` → 422.
- **Error handling** — the executor degrades gracefully (retrieval/graph/verification failures are caught, the answer still flows through the single pathway); cache probing never raises.

---

## 6. Optimization Framework

- **Adaptive policies** — a policy is a weight vector + flags (offline forces local models, max_compression caps context compression). Per-workspace, persisted, ML-ready (a learned policy produces the same vector).
- **Routing** — normalized multi-objective scoring across a provider-agnostic catalog; returns the winner + ranked candidates + rationale.
- **Caching** — answer cache (biggest lever) + observatory over existing module caches + adaptive LRU eviction.
- **Cost intelligence** — explainable, quantified recommendations ("switch to X: −80%", "reuse cache: −100%", "compress context", "reduce graph depth", "skip reranker").
- **Quality optimization** — a quality floor gates the router; citations are always preserved; verification confidence is recorded as `quality_impact` so quality-vs-cost is measurable.
- **Future extensibility** — `Optimizer`/`ModelProvider` protocols + the policy weight vector are the plug-in seams for ML-based optimization and new providers.

---

## 7. AI Integration

The engine reuses, never duplicates:

- **Evaluation Framework (M1)** — quality metrics inform the quality floor / recommendations (advisory).
- **Observability Platform (M2)** — the `CostTracker` + unified telemetry are the historical cost picture the Cost Intelligence engine analyzes (reused verbatim).
- **Retrieval Engine** — the RetrievalOptimizer produces params; execution runs the REAL `MultimodalRetrievalService` with them.
- **Context Engineering / PromptPackage** — ContextPlan/PromptPlan tune budget/compression/template; execution builds the REAL `PromptPackage`.
- **Knowledge Graph / Semantic Memory** — adaptive graph-hops feed the REAL `SemanticMemoryService`.
- **AnswerService** — the router SELECTS a model (for cost estimate + recommendation); actual inference still flows through the **single injected `answer_fn`** pathway. No second inference path.
- **Verification Engine** — every optimized run is verified; confidence becomes `quality_impact`.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/optimization`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/preview` | Full optimization plan (model + pipeline + recommendations + savings) — no execution |
| POST | `/recommend/model` | Model recommendation + ranked candidates + rationale |
| POST | `/recommend/pipeline` | Adaptive pipeline recommendation (retrieval/context/prompt) |
| POST | `/run` | Apply the plan through the REAL pipeline → answer + savings + run log |
| GET | `/dashboard` | Policy + cost analysis + cache + recent runs + quality-vs-cost |
| GET | `/cost` | Cost analysis (observability cost + optimization-run savings) |
| GET | `/quality-vs-cost` | Per-run quality/cost/savings points |
| GET | `/history` | Optimization run history |
| GET | `/cache` | Cache-layer statistics + adaptive recommendation |
| GET/PUT | `/policy` | Get / set the per-workspace optimization policy |

**Requests:** `{query, policy?}` (policy pattern-validated); `{policy}` for PUT.
**Errors:** 404 workspace, 401/403 unauthenticated, 422 bad policy.

---

## 9. Performance Optimizations

- **Cache-first** — an answer-cache hit short-circuits retrieval + context + inference + verification entirely (the largest single saving).
- **Adaptive routing** — cheap models + trimmed pipelines for simple queries; the funnel only widens when complexity/quality demand it.
- **Incremental optimization** — the decision layer (`preview`) is pure computation (profile + score), no I/O; only `run` touches the pipeline.
- **Parallel-safe** — optimizers are independent, pure functions over the profile; they can be evaluated concurrently.
- **Bounded** — LRU + TTL answer cache; catalog scoring is O(models); history/cost queries are workspace-scoped and limit-capped.
- **Large workspaces** — cost analysis reuses the observability unifier's bounded reads rather than scanning all logs.

---

## 10. Testing

- **`tests/test_optimization_unit.py` (10)** — profiler tiers, router (policy-weighted cheap-vs-quality, offline-forces-local), retrieval/context/prompt optimizers (adaptive + policy-capped compression + citation preservation), answer cache (LRU + TTL), cost-intelligence recommendations (+ cache-hit short-circuit), engine plan/savings, policy-weight normalization.
- **`tests/test_optimization_api.py` (6)** — preview + recommend, 422 on bad policy, **optimized run then cache-hit short-circuit** (real pipeline), cost + quality-vs-cost + cache + dashboard, per-workspace policy persistence (a no-policy preview then uses the persisted policy), auth.
- **Integration flow covered:** request → optimization engine → pipeline selection → retrieval → context → PromptPackage → AnswerService → Verification → OptimizationRunLog.
- **Regression** — 2 new models registered in `init_db` + conftest; `run` reuses the existing `get_agent_services` fake; the answer cache is cleared per-test via an autouse fixture. All Phase 1–8 M2 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/optimization/{__init__,interfaces,catalog,policy,profiler,router,optimizers,
cache_intel,cost_intel,engine,execute,models,repository,service,schemas,api,errors}.py`;
`tests/test_optimization_unit.py`; `tests/test_optimization_api.py`.

**Modified (backend)** — `app/db/base.py` (register 2 models), `app/main.py` (mount router),
`tests/conftest.py` (register models + mount router). *Purpose: make the new tables + routes discoverable — no prior-module source changed.*

**New (frontend)** — `src/api/optimization.ts`; `src/pages/OptimizationWorkspace.tsx`;
`src/styles/optimization.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

*(No prior-phase execution code was modified — the engine tunes parameters the existing services already accept, and selection/estimation is additive.)*

---

## 12. Future Compatibility

- **Module 4 — Continuous Learning & Feedback** — the `OptimizationRunLog` (estimated-vs-actual + quality_impact) and the policy weight vector are the training signal + the plug-in point for learned policies.
- **Self-optimizing AI systems** — the `Optimizer` protocol lets an RL/bandit optimizer replace the heuristic stages without touching the engine.
- **Enterprise AI cost governance** — per-workspace policies + the cost dashboard + savings ledger are the governance surface; the `enterprise` policy is the template.
- **Multi-LLM routing** — the provider-agnostic catalog is the seam: wiring a `ModelSpec` to a real provider client (behind the abstraction) turns the router's *selection* into *execution* with zero engine change.
- **Autonomous AI infrastructure** — preview (decide) + run (apply) + record (learn) is the closed loop autonomy needs.

---

## 13. Lessons Learned

- **Decision ≠ execution.** Separating the `OptimizationPlan` (pure data) from `apply_plan` (runs the real pipeline) is the key architectural choice: it makes optimization previewable, testable without inference, and safe (the plan only tunes parameters the existing services already accept — no new execution path, the single AnswerService pathway preserved).
- **Optimize by tuning, not replacing.** The retrieval/context/prompt optimizers emit *parameters*; the real Retrieval Engine / PromptPackage / AnswerService consume them. Nothing was reimplemented, so the 733-test surface carried zero regression risk.
- **Cache-first is the biggest lever.** A content-addressed answer cache short-circuits the entire pipeline; it's modeled as its own cache-decision stage so the saving (−100%) is explicit and measured.
- **Provider-agnostic from day one.** Routing scores whatever the catalog exposes; the Anthropic entries use current model IDs/pricing, others are representative — but the router has no `if provider == …`, so a real multi-provider client drops in behind the abstraction later.
- **Explainability makes optimization trustworthy.** Every recommendation carries a why + a quantified saving, and every run logs estimated-vs-actual — so a human (or a future auto-optimizer) can see *why* a choice was made and whether it paid off.
- **Tradeoffs / limitations.** The router *selects* a model and *estimates* cost; actual inference still runs the local AnswerService (wiring specs to real provider clients is the documented next step behind the `ModelProvider` seam). Complexity profiling is heuristic (length/keywords), not learned. OpenAI/Google catalog prices are representative, not live. Compression is deterministic (whitespace/length), not semantic. These are all plug-in points, not rewrites.
```
```
This completes Phase 8 Module 3 — LexiMind now optimizes every request before it runs: routing models,
adapting the pipeline, serving from cache, and recommending cost savings, all policy-driven and explainable.
