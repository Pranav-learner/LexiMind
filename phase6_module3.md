# Phase 6 — Module 3: Verification & Reasoning Engine

> **Status:** ✅ Complete · Backend `app/reasoning/` · auto-verification wired into every specialized agent · Frontend `VerificationInspector` + `VerificationPanel` · 27 new tests. Verification is deterministic + LLM-free by default; `thorough` mode adds exactly ONE optional critique through the single AnswerService pathway.

---

## 1. Module Overview

Modules 1–2 gave LexiMind agents that **retrieve and generate**. This module gives them the ability to
**reason about and verify** what they produced. After the single `AnswerService` writes a draft, the
Verification & Reasoning Engine validates every important claim against the retrieved evidence, detects
contradictions across sources and modalities, estimates **confidence from measurable system signals**
(not the LLM's self-report), validates citations, self-reviews the draft, and emits a structured,
explainable **VerificationReport**. It is the trust layer every future AI capability sits on.

**Generation vs evidence-based reasoning:**

| Generation (before) | Evidence-based reasoning (this module) |
|---|---|
| "The model said it, ship it." | Every important claim is checked against retrieved evidence. |
| Confidence = vibes / LLM self-report | Confidence = weighted, measurable signals (support ratio, retrieval quality, citation coverage, cross-source agreement…). |
| Citations trusted as-is | Citations validated (broken / missing / weak / duplicate) before returning. |
| Conflicts invisible | Contradictions detected across documents, lectures, meetings, images, notes. |
| No audit trail | A structured, explainable report + `VerificationLog` per run. |

Everything is deterministic and instant by default (no LLM, no torch) so verification is testable and
reproducible; a single optional model critique is available in `thorough` mode.

---

## 2. Previous Architecture

Before this module, an agent answer flowed:

```
User → Agent → Retrieval → Context → PromptPackage → AnswerService → Response
```

Limitations:
- **No claim-level grounding.** The whole answer was accepted or not; individual statements were never
  checked against the evidence that supposedly supported them.
- **No confidence.** Nothing told the user (or a downstream agent) how much to trust the result, and
  the only available signal would have been the model's own say-so.
- **Citations unchecked.** A `[3]` that pointed at nothing, or at low-confidence evidence, sailed through.
- **Conflicts silent.** Two sources disagreeing (or the answer contradicting a source) produced no warning.
- **No audit trail** for trust/governance.

---

## 3. New Architecture

```
User
  ↓
Agent (Module 2) → Retrieval → Context → PromptPackage → AnswerService → DRAFT
  ↓
Verification & Reasoning Engine  (consumes the draft + the evidence already retrieved)
  ├─ Claim extraction
  ├─ Evidence validation      → supported / weak / unsupported / conflicting
  ├─ Contradiction detection  → claim↔evidence + evidence↔evidence
  ├─ Citation validation      → broken / missing / weak / duplicate
  ├─ Confidence estimation    → weighted measurable signals
  ├─ Self review              → bounded (deterministic + optional 1× model critique)
  └─ Explanation              → structured reasoning metadata (no chain-of-thought)
  ↓
VerificationReport  →  attached to the agent result + persisted as VerificationLog
  ↓
Final Response (answer + trust metadata)
```

The engine adds **no** retrieval and **no** generation pipeline. It reuses the evidence Phases 1/2/4/5
already produced, and in `thorough` mode makes ONE optional pass through the same `answer_fn`.

---

## 4. Verification Pipeline

1. **Claim extraction** (`claims.py`) — segment the draft prose into checkable statements, parse `[n]`
   markers, drop headings/tables/code/questions/boilerplate.
2. **Evidence validation** (`evidence_validator.py`) — per claim, measure lexical coverage against the
   evidence pool → supported / weakly_supported / unsupported / conflicting. Works across every
   modality (document/image/diagram/OCR/audio/video/timeline) because it operates on the normalized
   `EvidenceRef.text` each modality contributes. A genuinely-overlapping `[n]` is rewarded.
3. **Contradiction detection** (`contradiction.py`) — promotes `conflicting` verdicts to
   claim↔evidence contradictions, and finds evidence↔evidence conflicts (same-subject sources that
   disagree in polarity or numbers, cross-document = higher severity).
4. **Citation validation** (`citation_validator.py`) — broken (index not in evidence), missing
   (substantive claim with no citation), weak (cited low-confidence evidence), duplicate (over-cited).
5. **Confidence estimation** (`confidence.py`) — `overall = Σ signal·weight` over measurable signals.
6. **Self review** (`self_review.py`) — bounded: deterministic recommendations always; `thorough`
   adds exactly one model critique through `answer_fn` (never loops, never re-answers).
7. **Explanation** (`explanation.py`) — structured "why" metadata (evidence selection, confidence,
   contradictions, citation accept/reject). No chain-of-thought is ever exposed.
8. **Report** (`interfaces.VerificationReport`) — assembles status + confidence + verdicts +
   contradictions + citation issues + missing evidence + warnings + recommendations + explanations.

**Precision note:** polarity conflict detection was deliberately made conservative — it fires only on
an explicit antonym pair or a negation attached to a *shared* keyword (so incidental negations like
"no preemption" don't false-positive a supported claim).

---

## 5. Backend Architecture

```
app/reasoning/
  textutil.py            deterministic primitives (keywords, coverage, jaccard, polarity, numbers)
  interfaces.py          Protocols + value objects (Claim/ClaimVerdict/Contradiction/CitationIssue/
                         ConfidenceBreakdown/VerificationReport) — the interface-driven seam
  claims.py              SentenceClaimExtractor
  evidence_validator.py  LexicalEvidenceValidator
  contradiction.py       HeuristicContradictionDetector
  confidence.py          SignalConfidenceEngine
  citation_validator.py  CitationIntegrityValidator
  self_review.py         SelfReviewEngine (+ recommendations_from)
  explanation.py         StructuredExplanationGenerator
  engine.py              ReasoningEngine (orchestrator + evidence normalization + content cache)
  models.py              VerificationLog (new table)
  repository.py          VerificationRepository
  service.py             VerificationService (verify / verify_task_result / verify_stored_task + reads)
  schemas.py             DTOs
  errors.py              transport-agnostic errors (status_code)
  api.py                 /workspaces/{id}/verification/*
```

- **Interfaces / DI** — every stage is a Protocol; `ReasoningEngine` takes injectable stages (defaults
  are the deterministic implementations) so an NLI/embedding/LLM backend swaps in without touching the
  engine. The API reuses Module-1 `get_agent_services` for the (optional, thorough-only) `answer_fn` —
  one inference surface, and tests override it with a fake.
- **Caching** — a content-addressed LRU keyed by `sha1(mode + answer + evidence)` skips re-verifying an
  identical triple; validators memoize per-claim coverage and per-pair contradiction checks; a perf cap
  bounds pairwise contradiction work on huge evidence pools.
- **Validation / errors** — Pydantic request bounds + a `mode` pattern; `VerificationNotFound` → 404.
- **Error handling** — verification is advisory: in the agent path it degrades to a warning stub and
  never crashes or fails the task.

---

## 6. Frontend Architecture

- **`components/verification/VerificationPanel.tsx`** — reusable inspector: status + confidence badge,
  confidence-signal bars, claim→evidence mapping (colour-coded by verdict), evidence tree,
  contradictions, citation validation, warnings/recommendations/self-review, and structured reasoning
  metadata. Sub-tabbed (overview / claims / evidence / contradictions / citations / reasoning).
- **`pages/VerificationInspector.tsx`** — developer/debug page at `/workspace/:id/verification`:
  workspace verification history + stats + the selected report (also deep-links `?task=<id>`).
- **Agent Workspace integration** — the report arrives inline on every agent-task response
  (`TaskResult.verification`), so the Agent Workspace shows a **confidence badge** in the result header
  and a **verification tab** rendering the same `VerificationPanel` — the "Why this answer?" panel.
- **State / routing** — local React state; lazy route + a hub link (🛡️ Verification Inspector). Default
  agent UX stays clean; the deep inspector is opt-in.

---

## 7. AI Integration (no duplicate pipelines)

```
Agent Runtime → Retrieval → Context → PromptPackage → AnswerService → DRAFT
                                                             ↓
                                        Verification Engine (reuses the draft + retrieved evidence)
                                                             ↓  (thorough: 1× answer_fn critique)
                                                     Final Response + trust metadata
```

- Reuses the **evidence** Module-2 agents already gathered (`AgentTaskResult.evidence`) — **no
  re-retrieval**.
- Reuses **Citation Intelligence's philosophy** (deterministic, evidence-grounded explanations) for
  citation validation + the explanation engine.
- Reuses the **single AnswerService pathway** (`ctx.answer_fn`) only for the optional thorough critique
  — never a second orchestration.
- Integration point: `AgentTaskService.run_task` auto-verifies after `agent.run(...)` (configurable
  `verify` = off | fast | thorough), attaches the report to the result, and writes a `VerificationLog`.

---

## 8. Confidence & Verification Strategy

- **Evidence scoring** — retrieval score carried from Phase 1/4/5 is the `EvidenceRef.score`.
- **Claim validation** — lexical coverage thresholds (supported ≥ 0.6, weak ≥ 0.3) + citation credit;
  conflict requires real subject overlap + a polarity/number clash.
- **Confidence** — `overall = Σ value·weight` over: support_ratio (.30), retrieval_quality (.18),
  citation_coverage (.18), cross_source_agreement (.15), evidence_sufficiency (.12), execution_success
  (.07). Bands: high ≥ .75, moderate ≥ .5, else low.
- **Contradiction detection** — antonym pairs + shared-keyword-negation + numeric mismatch, over the
  claim↔evidence and evidence↔evidence surfaces.
- **Citation validation** — broken/missing/weak/duplicate, with a health rollup.
- **Extensibility** — swap any Protocol implementation (e.g. an NLI validator, an embedding coverage
  scorer, an LLM judge) without changing the engine or the API.

---

## 9. API Documentation

All routes under `/workspaces/{workspace_id}/verification`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/verify` | Ad-hoc verify `{answer, evidence[], mode, signals, persist}` → report |
| POST | `/tasks/{task_id}/verify` | Re-verify a stored agent task → report |
| GET | `` | Verification history |
| GET | `/stats` | Counts + avg confidence |
| GET | `/tasks/{task_id}` | Latest verification for a task (detail incl. report) |
| GET | `/{verification_id}` | Verification detail (incl. report) |
| GET | `/{verification_id}/confidence` | Confidence breakdown slice |
| GET | `/{verification_id}/contradictions` | Contradictions slice |
| GET | `/{verification_id}/citations` | Citation issues slice |
| GET | `/{verification_id}/evidence-map` | Evidence + claim→evidence mapping |
| GET | `/{verification_id}/explanation` | Structured reasoning metadata |

**Report shape:** `{status, mode, confidence{overall,band,signals[],per_section,per_claim,explanation},
claims_total, counts{supported,weakly_supported,unsupported,conflicting}, supported_ratio,
claim_verdicts[], contradictions[], citation_issues[], missing_evidence[], warnings[],
recommendations[], review_notes[], explanations{}, evidence[], timings{}}`.

**Errors:** 404 unknown workspace/verification/task, 401/403 unauthenticated, 422 bad mode.

---

## 10. Performance Optimizations

- **Content cache** — identical `(mode, answer, evidence)` returns the cached report (LRU 256).
- **Parallel-ready / incremental** — per-claim validation is independent (memoized coverage); the
  pairwise contradiction scan is capped (`MAX_PAIRS`) so large evidence pools stay bounded.
- **Avoid repeated verification** — the agent path verifies the evidence it already has; re-verification
  reuses the persisted deliverable's citations.
- **LLM-free by default** — `fast` mode does zero inference; `thorough` is bounded to one call.
- **Large responses/reports** — claim extraction + validation are linear in answer length; evidence is
  truncated for prompts and previews.

---

## 11. Testing

- **`tests/test_verification_unit.py` (17)** — text primitives (coverage/jaccard/polarity incl. the
  "no preemption" false-positive guard/numeric), claim extraction (citation parsing + noise skipping),
  evidence validator (all four statuses + empty pool), contradiction detector (evidence↔evidence +
  claim↔evidence + cross-doc severity), confidence engine (weights sum to 1, `overall = Σ contribution`,
  per-claim, low-evidence floor), citation validator (broken/missing/weak), self review (fast +
  thorough bounded to ONE model call), recommendations, explanation (structured, no CoT), engine status
  (verified/warning/failed) + cache identity + evidence normalization/re-indexing.
- **`tests/test_verification_api.py` (10)** — ad-hoc verify + persist + history + detail + all report
  slices; conflict detection; thorough model review; no-persist; **agent auto-verification** (task
  response carries a report + a `VerificationLog` is queryable by task id); `verify=off` skips it;
  re-verify a stored task; stats; 404; auth.
- **Regression** — Module 2's agent-task path now auto-verifies; all existing Phase 1–6 M2 tests
  continue to pass (full suite green). New model `VerificationLog` registered in `init_db` + conftest.

---

## 12. File Changes Summary

**New (backend)** — `app/reasoning/{__init__,textutil,interfaces,claims,evidence_validator,
contradiction,confidence,citation_validator,self_review,explanation,engine,models,repository,service,
schemas,errors,api}.py`; `tests/test_verification_unit.py`; `tests/test_verification_api.py`.

**Modified (backend)** — `app/db/base.py` (register `VerificationLog`), `app/main.py` (mount router),
`tests/conftest.py` (register model + mount router), `app/agents/specialized/base.py`
(+`AgentTaskResult.verification`), `app/agents/task_service.py` (auto-verify in `run_task`),
`app/agents/task_schemas.py` (+`verify` mode field), `app/agents/task_api.py` (thread `verify` param).

**New (frontend)** — `src/api/verification.ts`; `src/components/verification/VerificationPanel.tsx`;
`src/pages/VerificationInspector.tsx`; `src/styles/verification.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link),
`src/pages/AgentWorkspace.tsx` (confidence badge + verification tab),
`src/api/researchAgents.ts` (`TaskResult.verification`).

---

## 13. Future Compatibility

- **Module 4 — Multi-Agent Orchestration** — a Verifier agent can wrap the engine; confidence/status
  become routing signals ("re-run research if confidence < 0.5"); the report is the artifact agents
  hand each other.
- **Knowledge Graph** — claim↔evidence verdicts and contradictions are edges ready for a graph.
- **Enterprise AI / governance / compliance** — `VerificationLog` is the audit trail (who claimed what,
  supported by which evidence, at what confidence); citation validation enforces grounding policies.
- **Autonomous research** — the confidence + gap + contradiction signals are the control loop for
  "keep researching until verified".
- **Pluggable reasoning** — every stage is a Protocol; an NLI/embedding/LLM-judge backend drops in with
  no API or engine change.

---

## 14. Lessons Learned

- **Measure, don't ask.** Confidence from measurable signals (support ratio, retrieval quality, citation
  coverage, cross-source agreement) is far more trustworthy and testable than LLM self-reported
  confidence — and it needs no inference.
- **Determinism first, LLM optional.** Building the whole pipeline LLM-free made it instant, cacheable
  and unit-testable; `thorough` mode layers a single bounded critique on top without changing the
  contract.
- **Heuristics need precision guards.** The first polarity-conflict heuristic (negation parity)
  false-positived on incidental negations ("no preemption"); tightening it to antonyms + shared-keyword
  negation removed the noise. Verification that cries wolf is worse than none.
- **Reuse the evidence, don't re-fetch.** Verifying the evidence the agent already gathered keeps the
  single retrieval + single inference guarantees intact and makes verification nearly free.
- **Tradeoffs / limitations.** Lexical coverage is a proxy for semantic entailment — an embedding/NLI
  backend (behind the same Protocol) would catch paraphrase support/contradiction the lexical validator
  misses; contradiction detection is pairwise-capped for scale; `thorough` critique text is advisory
  metadata, not parsed into logic.
- **Future improvements.** NLI-based entailment, embedding coverage scoring, cross-asset persisted-
  citation validation via Citation Intelligence, and streaming verification progress over the existing
  event sink.
