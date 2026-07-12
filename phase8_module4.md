# Phase 8 — Module 4: Continuous Learning & Feedback Platform

> **Status:** ✅ Complete · Backend `app/learning/` · Frontend `LearningWorkspace` · 14 new tests. The final Phase-8 module closes the loop: Response → **Feedback** → **Learning Engine** → **Analysis** → **Recommendations** → **Human Review** → (future) Improvement. It CONSUMES failure signals from every subsystem (feedback + VerificationLog + AgentTaskLog + OptimizationRunLog) and PRODUCES explainable, GOVERNED recommendations for prompts / retrieval / agents / datasets — and **never auto-modifies production behavior** (every change passes through the human review queue).

---

## 1. Module Overview

LexiMind could retrieve, reason, orchestrate, evaluate, observe, and optimize — but it did not **learn from real-world usage**. This module is the continuous-improvement engine (the pattern behind Copilot/Cursor/Notion AI feedback loops), built natively into LexiMind.

It is **NOT** about retraining language models. It builds the infrastructure that continuously improves Retrieval, Prompting, Routing, the Knowledge Graph, Evaluation datasets, Agent workflows, and Context Engineering — by turning feedback + failures into governed, explainable recommendations.

**Optimization (M3) vs continuous learning (M4):**

| Optimization (M3) | Continuous Learning (M4) |
|---|---|
| Acts *within* a request (route, cache, compress) | Learns *across* requests over time |
| Automatic, per-request | Asynchronous, cross-request, governed |
| Tunes parameters live | Proposes improvements for humans to approve |
| No human in the loop | Human review is mandatory (safety) |
| Optimizes the *current* pipeline | Improves the *future* pipeline (prompts, datasets, workflows) |

---

## 2. Previous Architecture

```
User → Request → AI Pipeline → Response
```

Improvement before this module was **manual**: a developer noticed a bad answer, hand-wrote an eval item, tweaked a prompt. There was no structured feedback surface, no automatic failure analysis, no failure→benchmark pipeline, no recommendation engine, no governed review. Signals existed (verification failures, agent errors, optimization runs) but were never aggregated into *what should improve and why*.

---

## 3. New Architecture

```
Response
   ↓
Feedback  (thumbs / star / text / correction / citation — auth or anon)
   ↓
Learning Engine
   ↓
Error Analysis  ── collect signals (feedback + VerificationLog + AgentTaskLog + OptimizationRunLog)
   ↓                categorize → cluster
Recommendations ── prompt / retrieval / agent / dataset / routing learners (explainable)
   ↓
Human Review Queue  (pending → approve | reject — auditable, NEVER auto-applied)
   ↓
Future Improvements  (dataset updates now; prompt/routing changes are proposals)
```

The engine consumes every subsystem's output and produces governed proposals; a `LearningCycleLog` records each cycle.

---

## 4. Continuous Learning Pipeline

1. **Feedback Collection** (`feedback.py`) — one structured store for every feedback kind, authenticated or anonymous; derives sentiment so negative feedback is a first-class failure signal.
2. **Error Analysis** (`analyzer.py`) — collect failure signals from feedback + the existing logs, categorize (hallucination / missing_retrieval / bad_citation / slow_response / agent_failure / low_confidence / negative_feedback), cluster by category + keyword signature.
3. **Dataset Generation** (`dataset_builder.py`) — materialize failures + corrections into `EvalDataset`/`EvalItem` (reuses the Evaluation Framework) — every important failure becomes a regression test.
4. **Prompt Learning** (`learners.py`) — recommend grounding-instruction tightening, A/B versions, promotion/retirement (never edits prompts).
5. **Retrieval Learning** — recommend K/graph/chunking/fusion changes (never edits retrieval).
6. **Agent Learning** — recommend planner/tool-selection/routing changes (never rewrites agent logic).
7. **Recommendation Engine** (`engine.py`) — aggregate + de-dup explainable recommendations.
8. **Human Review** (`review.py`) — approve/reject with audit; nothing is auto-applied.

---

## 5. Backend Architecture

```
app/learning/
  interfaces.py      FailureSignal / FailureCluster / LearningRec + LearningSource protocol
  models.py          Feedback / LearningRecommendation (review queue + audit) / LearningCycleLog
  feedback.py        FeedbackManager — unified feedback (auth + anonymous) + sentiment + summary
  analyzer.py        ErrorAnalyzer — collect failure signals from logs + feedback, categorize, cluster
  learners.py        Prompt / Retrieval / Agent learning engines (recommend, never modify)
  dataset_builder.py DatasetBuilder — failures → EvalDataset/EvalItem (reuses Evaluation Framework)
  review.py          HumanReviewQueue — approve/reject with audit (governance)
  engine.py          LearningEngine — one cycle: analyze → recommend → persist pending → log
  repository/service/schemas/api/errors  data access + orchestration + DTOs + routes
```

- **Interfaces / DI** — each learner implements the `LearningSource` protocol (`analyze(signals, clusters) → recs`); a future RL/active-learning engine plugs in by implementing the same protocol. The engine iterates `self.sources` — adding a learner is one list entry.
- **Repositories / services** — `LearningRepository` (cycle logs + recommendation aggregates); `LearningService` orchestrates feedback/insights/cycle/review/dataset/report.
- **Validation / errors** — Pydantic patterns on feedback kind/target/rating (422 on bad input); `RecommendationNotFound` → 404.
- **Error handling** — the analyzer reads each log source defensively (getattr + try/except) so a missing/changed column degrades gracefully rather than failing the cycle.

---

## 6. Learning Framework

- **Feedback sources** — thumbs / star / text / correction / citation / retrieval / agent / graph / media / workspace, auth or anonymous.
- **Learning cycles** — analyze → recommend → persist pending → `LearningCycleLog`; idempotent and asynchronous (off the request path).
- **Recommendation pipeline** — every rec carries **reason + evidence + expected impact + confidence + affected components** (Step 10 contract).
- **Approval workflow** — recommendations enter `pending`; a developer `approve`/`reject`s; the transition is stamped with reviewer + timestamp + note (auditable version history).
- **Governance (Step 16)** — the system NEVER changes production behavior automatically; approval records intent only. Analysis → evidence → human review → approval → (future) deployment.
- **Future extensibility** — the `LearningSource` protocol is the RLHF/active-learning seam; the recommendation record is the enterprise-approval-workflow seam.

---

## 7. AI Integration

Continuous Learning consumes every subsystem, reusing (never duplicating):

- **Evaluation Framework (M1)** — the Dataset Builder writes failures back into `EvalDataset`/`EvalItem` (the same tables the eval runner consumes).
- **Observability (M2) / Optimization (M3)** — reads `OptimizationRunLog` (latency/quality) as slow-response/optimization signals.
- **Verification Engine** — reads `VerificationLog` (unsupported / contradictions / citation_failures / confidence) as hallucination / bad-citation / low-confidence signals.
- **Agent Runtime** — reads `AgentTaskLog` (success / error / retries) as agent-failure signals.
- **Retrieval / Context / PromptPackage / Knowledge Graph** — named as `affected_components` in retrieval/prompt/graph recommendations (the improvement targets).
- **AnswerService** — untouched; there is no new execution path — the learning engine only reads outputs and recommends.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/learning`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/feedback` | Submit structured feedback |
| GET | `/feedback?sentiment=` · `/feedback/summary` | Feedback history / rollup |
| GET | `/insights` | Failure categories + clusters + feedback summary |
| POST | `/generate` | Preview recommendations (no persistence) |
| POST | `/cycle` | Run a learning cycle → persist pending recs + log |
| GET | `/recommendations?status=&category=` · `/recommendations/{id}` | Review queue / detail |
| POST | `/recommendations/{id}/approve` · `/reject` | Governed review (auditable) |
| POST | `/dataset` | Build a failure regression dataset (reuses Evaluation) |
| GET | `/report` · `/dashboard` | Improvement report / full dashboard |

**Requests:** feedback `{target_type, target_id?, kind, rating?, comment?, correction?}` (pattern/range-validated); review `{note}`.
**Errors:** 404 workspace/recommendation, 401/403 unauthenticated, 422 bad feedback.

---

## 9. Performance Optimizations

- **Asynchronous learning** — the cycle reads logs + feedback and is fully decoupled from the user-request path; it never slows an answer.
- **Incremental analysis** — signal collection is bounded per-source (limit-capped `desc(created_at)` reads); clustering is O(signals).
- **Failure clustering** — a keyword+category signature collapses similar failures so recommendation generation scales with *distinct* problems, not raw volume.
- **Batch-friendly** — `generate` (preview) is pure computation; only `cycle` persists — so a scheduler/worker can batch cycles cheaply.
- **Large workspaces** — every read is workspace+owner scoped and limited; the analyzer degrades gracefully if a source table is huge or absent.

---

## 10. Testing

- **`tests/test_learning_unit.py` (8)** — feedback sentiment derivation, feedback summary (incl. anonymous rows), analyzer categorization + clustering (critical sorts first), the three learners (recommend on hallucination / recall-gap / agent-failures; empty on no signals), dataset builder (a correction becomes a golden `EvalItem`).
- **`tests/test_learning_api.py` (6)** — feedback submit + sentiment + summary, 422 on bad feedback, **full learning cycle → governed pending recommendations → approve (audited) / reject** (the safety invariant), 404 on unknown recommendation, dataset build + improvement report + dashboard, auth.
- **Integration flow covered:** request → AI pipeline → feedback → learning analysis → recommendations → review queue → LearningCycleLog.
- **Regression** — 3 new models registered in `init_db` + conftest; the analyzer reads existing logs defensively. All Phase 1–8 M3 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/learning/{__init__,interfaces,models,feedback,analyzer,learners,dataset_builder,
review,engine,repository,service,schemas,api,errors}.py`; `tests/test_learning_unit.py`;
`tests/test_learning_api.py`.

**Modified (backend)** — `app/db/base.py` (register 3 models), `app/main.py` (mount router),
`tests/conftest.py` (register models + mount router). *Purpose: make the new tables + routes discoverable — no prior-module source changed.*

**New (frontend)** — `src/api/learning.ts`; `src/pages/LearningWorkspace.tsx`; `src/styles/learning.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

*(No prior-phase execution code was modified — the learning engine only reads outputs and records feedback + proposals.)*

---

## 12. Future Compatibility

- **Phase 9 — Enterprise Collaboration & Deployment** — the recommendation record + review queue are the approval/audit surface; multi-reviewer workflows plug into the status transition.
- **Human-in-the-loop AI** — the review queue *is* the HITL surface; approval records are the audit trail.
- **Active Learning** — the Dataset Builder + failure clusters are the active-learning candidate selector (label the hardest failures first).
- **RLHF (future)** — feedback (sentiment + corrections) + `LearningCycleLog` (quality signal) are the reward data; the `LearningSource` protocol is where a policy-learning engine attaches.
- **Org-wide AI governance / autonomous improvement** — governance is enforced by design (no auto-apply); a future "deployment" stage turns an *approved* recommendation into an applied change behind the same review record, with rollback via version history.

---

## 13. Lessons Learned

- **Consume signals, don't re-instrument.** The analyzer treats the existing `VerificationLog` / `AgentTaskLog` / `OptimizationRunLog` (plus this module's feedback) as failure sources — so continuous learning became possible with zero new instrumentation in the subsystems it learns from (defensive getattr reads keep it robust to schema drift).
- **Governance is architectural, not a checkbox.** Recommendations are inert records with a `status` — the *only* way to act on one is a human `approve`/`reject`. There is no code path that mutates production from a recommendation, which is the strongest possible form of the Step-16 safety guarantee.
- **Every failure becomes a benchmark.** Wiring the Dataset Builder to the *existing* eval tables (not a parallel dataset store) means a corrected answer immediately becomes a regression test the Evaluation runner can score — closing the loop back to Module 1.
- **Explainability is the product.** A recommendation without reason + evidence + expected impact + confidence + affected components is not actionable; making that the value-object contract (`LearningRec`) forced every learner to justify itself.
- **Pluggable learners keep the engine stable.** The `LearningSource` protocol means adding retrieval/agent/RL learners is a list entry, not an engine change — the orchestrator, review queue, and cycle log never move.
- **Tradeoffs / limitations.** Failure categorization + clustering are heuristic (keyword signature), not semantic embeddings. Recommendations are generated from aggregate counts, not per-case root-cause. "Deployment" of an approved recommendation is future work (approval records intent; nothing is applied yet) — deliberately, to keep the safety guarantee absolute. Learning cycles are triggered on demand / by API; a scheduled background worker is the next step.
```
```
This completes Phase 8 Module 4 — and Phase 8. LexiMind now learns from real-world usage: collecting
feedback, analyzing failures, generating explainable improvement recommendations, turning failures into
benchmarks, and routing every proposal through a governed human-review queue — never changing production on
its own.
