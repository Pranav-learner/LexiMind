# Phase 8 — Module 1: AI Evaluation & Benchmarking Framework

> **Status:** ✅ Complete · Backend `app/evaluation/` · Frontend `EvaluationWorkspace` · 21 new tests. Benchmarks execute the REAL production pipelines; retrieval Recall@K/Precision@K/MRR are computed by REUSING the existing `app.eval.RetrievalEvaluator` (not re-implemented); the LLM judge reuses the single `answer_fn`. No AI pipeline is duplicated.

---

## 1. Module Overview

LexiMind became extremely capable — but there was no objective way to answer "is retrieval getting
better?", "did prompt v7 improve answers?", "graph vs hybrid retrieval?", "did this deploy regress?".
This module makes LexiMind **measurable**: golden datasets, reproducible benchmarks over the real
pipelines, objective retrieval + generation metrics, LLM-assisted qualitative judgment, regression
detection, A/B pipeline comparison, and CI quality gates.

**Traditional testing vs AI evaluation:**

| Traditional testing | AI evaluation (this module) |
|---|---|
| Pass/fail on fixed assertions | Graded metrics on a golden dataset (Recall@K, NDCG, hallucination rate…) |
| Deterministic code paths | Probabilistic AI pipelines scored against ground truth |
| "Did it crash?" | "Did quality improve or regress vs the last version?" |
| One right answer | A distribution of quality signals + an LLM-judge second opinion |

This is offline/online *evaluation* — production monitoring is Module 2.

---

## 2. Previous Architecture

Quality was measured only by unit/integration tests (correctness) and a single low-level retrieval
`app.eval.framework` (Recall@K/Precision@K/MRR over a hand-loaded JSON dataset, used ad-hoc). There was
no persisted golden dataset, no benchmark over the *real* answer pipeline, no generation/hallucination
metrics, no regression detection, no A/B comparison, and no CI gate. "Better" was a matter of vibes.

---

## 3. New Architecture

```
Golden Dataset (persisted, versioned)
        ↓
Benchmark Runner  ── executes the REAL pipeline per item (retrieval / graph / temporal / answer)
        ↓
Metric Engine  ── Recall@K/Precision@K/MRR (REUSED app.eval.RetrievalEvaluator) + NDCG/MAP/hit-rate
                  + citation accuracy + ground-truth match + hallucination rate (reused Verification Engine)
                  + efficiency; optional LLM judge (reused answer_fn)
        ↓
Regression Detection (vs previous run) + CI Gate (thresholds)
        ↓
Benchmark Report → EvaluationRunLog (reproducible)  +  Pipeline Comparison (A/B)
```

---

## 4. Evaluation Pipeline

1. **Dataset management** (`datasets.py`) — create/import/export/version/validate golden items
   (question + ground truth + relevant chunks/entities + expected citations + difficulty). JSON portable.
2. **Benchmark runner** (`runner.py`) — runs the real pipeline per item, computes metrics, caches per
   (pipeline, version, dataset_version, item) for incremental re-runs, and **reuses
   `app.eval.RetrievalEvaluator`** for Recall@K/Precision@K/MRR over the already-computed outputs.
3. **Metrics** (`metrics.py`) — interface-driven `Metric`s: ranking (NDCG/MAP/hit-rate), citation
   accuracy, ground-truth match (reuses Module-3 lexical coverage), evidence coverage, hallucination
   rate + verification score (reuses the Verification Engine's output), efficiency (latency/tokens/context).
4. **LLM judge** (`judge.py`) — an ADDITIONAL signal (never a replacement): scores quality/completeness/
   relevance/citation and does A/B comparison, reusing the single `answer_fn`; parsed deterministically.
5. **Regression detection** (`regression.py`) — direction-aware per-metric deltas (higher-vs-lower-is-
   better) → improved/stable/regressed + a threshold **CI gate**.
6. **Pipeline comparison** — A/B two runs → per-metric winner.
7. **Report generation** — every run persists an `EvaluationRunLog` (metrics + per-item + regression + gate).

---

## 5. Backend Architecture

```
app/evaluation/
  models.py      EvalDataset / EvalItem / EvaluationRunLog
  interfaces.py  Pipeline/Metric/Judge protocols + value objects (EvalItemInput/PipelineOutput/…)
  datasets.py    DatasetManager (create/import/export/version/validate)
  pipelines.py   benchmarkable pipelines (run the REAL services) + registry
  metrics.py     MetricEngine (new metrics; recall/precision/mrr reused from app.eval)
  judge.py       LLMJudge (reuses answer_fn; A/B compare)
  runner.py      BenchmarkRunner (+ RetrievalEvaluator reuse + cache)
  regression.py  RegressionDetector + PipelineComparator + CI gate
  cache.py       EvaluationCache (incremental re-runs)
  repository/service/schemas/api  data access + orchestration + DTOs + routes
  errors.py      transport-agnostic errors (status_code)
```

- **Interfaces / DI** — pipelines, metrics, and the judge are replaceable Protocols; the runner depends
  only on them. The API reuses Module-1 `get_agent_services` (single answer function) for the answer
  pipeline + judge — tests override it with a fake.
- **Reuse** — `app.eval.RetrievalEvaluator` (retrieval metrics), the Verification Engine (hallucination/
  confidence), Module-3 `textutil.coverage` (ground-truth match), and every retrieval service (executed
  as the real pipeline). No metric/retrieval/inference logic is duplicated.
- **Caching** — content-addressed per (pipeline, version, dataset_version, item); a version bump
  invalidates automatically → incremental evaluation.
- **Validation / errors** — Pydantic bounds + difficulty pattern; `DatasetNotFound`/`RunNotFound`/
  `PipelineNotFound` → 404, `InvalidDataset` → 422.

---

## 6. Evaluation Framework

- **Metrics** — objective (Recall@K, Precision@K, MRR, NDCG@K, MAP, Hit-Rate, citation accuracy,
  ground-truth match, evidence coverage, hallucination rate, verification score, latency, tokens,
  context) + a subjective LLM-judge overall. Custom metrics = a class implementing `Metric`.
- **Datasets** — versioned golden sets; editing bumps the version for reproducibility.
- **Benchmarks** — reproducible: an `EvaluationRunLog` pins pipeline+version, dataset+version, model, the
  full metric set, cost/latency, and the report.
- **Regression strategy** — auto-baseline (previous run of the same pipeline+dataset); direction-aware;
  tolerance-based; CI gate on regression OR absolute-threshold violation.
- **Pipeline comparison** — per-metric A/B winner.
- **Quality scoring** — the aggregate metric set + gate is the quality score; the dashboard trends it.
- **Extensibility** — new pipelines/metrics/judges register with no runner change.

---

## 7. AI Integration

Evaluation executes the **real** production pipelines (Step 14):
- `workspace_retrieval` → Phase-1/4 unified retrieval (`MultimodalRetrievalService`).
- `graph_retrieval` → Phase-7 `SemanticMemoryService`.
- `temporal_retrieval` → Phase-5 `TemporalRetrievalService`.
- `answer` → unified retrieval → `PromptPackage` → single `answer_fn` (AnswerService) → Verification Engine.

The LLM judge and answer pipeline use the SAME single `answer_fn`. No shadow/duplicated execution path;
evaluation runs what production runs.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/evaluation`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/datasets` · `/datasets/import` | Create / import a golden dataset |
| GET | `/datasets` · `/datasets/{id}/export` | List / export datasets |
| GET | `/pipelines` | List benchmarkable pipelines |
| POST | `/run` | Run a benchmark (`dataset_id`, `pipeline`, `use_judge`, `thresholds`) → metrics + regression + gate |
| GET | `/runs` · `/runs/{id}` | Run history / detail |
| POST | `/runs/{id}/regression` | Regression report vs a baseline run |
| POST | `/compare` | A/B compare two runs |
| GET | `/dashboard` | Quality dashboard (counts, regressions, gate failures, recent, cache) |

**Run response:** `{id, pipeline, metrics{…}, item_count, duration_ms, cost_estimate, token_usage,
regression_status, gate{passed,reasons}, regression{deltas[]}, items[]}`.
**Errors:** 404 workspace/dataset/run/pipeline, 422 invalid dataset, 401/403 unauthenticated.

---

## 9. Performance Optimizations

- **Incremental evaluation** — the content-addressed cache skips re-running unchanged (pipeline, dataset)
  items; a version bump invalidates.
- **Reuse over recompute** — retrieval metrics reuse `app.eval` over already-computed outputs (no
  pipeline re-execution for the retrieval report).
- **Parallel-ready** — items are independent; the runner is structured for a session-per-item threadpool.
- **Large datasets** — per-item streaming aggregation; the report stores compact per-item summaries.
- **Resume-ready** — every run is a persisted log; a future resumable runner keys off cached item results.

---

## 10. Testing

- **`tests/test_evaluation_unit.py` (11)** — metric engine (ranking + generation + skip-when-unlabelled),
  LLM judge (parse + graceful degrade + A/B), regression (direction-aware + status + CI gate),
  comparator, dataset validation, eval cache (version invalidation), and the runner (aggregate + **reused
  RetrievalEvaluator** recall/mrr).
- **`tests/test_evaluation_api.py` (10)** — dataset lifecycle (create/list/export/import) + validation 422,
  pipeline list, **run a real retrieval benchmark** (+ second run gets an auto-baseline + regression),
  **run the answer pipeline** (with verification), CI gate + judge, history/regression/compare/dashboard,
  404s, auth.
- **Regression** — new models registered in `init_db` + conftest; run endpoints reuse the existing
  `get_agent_services` fake. All Phase 1–7 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/evaluation/{__init__,models,interfaces,datasets,pipelines,metrics,judge,runner,
regression,cache,repository,service,schemas,api,errors}.py`; `tests/test_evaluation_unit.py`;
`tests/test_evaluation_api.py`.

**Modified (backend)** — `app/db/base.py` (register 3 models), `app/main.py` (mount router),
`tests/conftest.py` (register models + mount router).

**New (frontend)** — `src/api/evaluation.ts`; `src/pages/EvaluationWorkspace.tsx`; `src/styles/evaluation.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

*(No prior-phase source files were modified beyond wiring — evaluation composes the existing pipelines.)*

---

## 12. Future Compatibility

- **Module 2 — AI Observability & Monitoring** — the `EvaluationRunLog` + metric trends are the offline
  counterpart to production monitoring; the metric engine is shared.
- **Module 3 — AI Optimization & Cost Intelligence** — cost/latency/token metrics + A/B comparison are the
  inputs to optimization decisions.
- **Module 4 — Continuous Learning & Feedback** — golden datasets + LLM-judge signals feed labelled data
  back into training/tuning.
- **Enterprise AI quality gates** — the CI gate (`gate_passed` + thresholds) is a deployment guard.
- **Continuous evaluation pipelines** — the reproducible runs + cache + regression are nightly/PR-benchmark
  ready.

---

## 13. Lessons Learned

- **Reuse the retrieval evaluator.** Recall@K/Precision@K/MRR already existed in `app.eval` — feeding it
  the already-computed outputs (a cached `retrieve_fn`) reused its math with zero re-execution and zero
  duplication, exactly the "never duplicate" mandate.
- **Evaluation must run production.** Benchmark pipelines call the real `MultimodalRetrievalService` /
  `SemanticMemoryService` / `TemporalRetrievalService` / `answer_fn` + Verification Engine — so a metric
  improvement is a *real* improvement, not a shadow-path artifact.
- **Hallucination for free.** Reusing the Verification Engine's supported/unsupported counts turned
  hallucination rate into a first-class metric with no new NLI logic.
- **Judge as a second opinion, not a verdict.** The LLM judge is opt-in and additive; objective metrics
  remain the source of truth, and the judge parses deterministically (neutral on malformed output).
- **Direction-aware regression is the whole trick.** Classifying each metric higher-vs-lower-is-better
  makes "latency up = bad" and "recall down = bad" fall out of one comparison, powering both regression
  detection and A/B comparison and the CI gate.
- **Tradeoffs / limitations.** Ground-truth match is lexical coverage (an embedding/entailment scorer is
  the upgrade behind the same `Metric` interface); benchmarks run synchronously (a threadpool/distributed
  runner is the scale path, and the cache + run logs make it resumable); the LLM judge quality depends on
  the judging model. Dense-vs-sparse isolation is a retrieval-request config rather than separate
  pipelines today — extensible via new registered pipelines.
```
```
This completes Phase 8 Module 1 — LexiMind is now a *measurable* AI platform with reproducible
benchmarks, regression detection, and CI-ready quality gates.
