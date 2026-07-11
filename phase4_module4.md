# Phase 4 — Module 4: Multimodal Context Engineering Engine

> Status: ✅ Complete. Backend (13 files, the Phase-2 evolution + 1 table) + frontend (3 files) + 2
> test suites (21 new tests, all passing; **409 total tests green** with no regressions across Phase
> 1/2, all of Phase 3, and Phase 4 Modules 1–3).

---

## 1. Module Overview

**Why multimodal context engineering is necessary.** Module 3 can now *retrieve* evidence from every
modality — but retrieval just returns a ranked list. The LLM sees only what we choose to put in its
prompt, and the context window is finite. Deciding **what deserves the model's attention**, across
text, OCR, diagrams, charts, tables, and metadata, and packing it into a coherent, budgeted, cited
prompt — that is context engineering. This module is the multimodal evolution of Phase 2.

**Retrieval vs context engineering.** Retrieval answers *"what is relevant?"* (a scored list).
Context engineering answers *"what, of the relevant, actually goes to the model, in what form, in what
order, within the token budget, and how is it cited?"* It deduplicates across modalities, ranks
heterogeneous evidence on one scale, allocates the budget by intent, compresses to fit, assembles an
adaptive layout, and builds a deterministic, inspectable prompt.

**How multimodal prompts improve answer quality.** A question about a system architecture should put
the **diagram** (its nodes/edges) first, then supporting text, then the relevant table — not three
paragraphs that merely mention it. Giving the model the actual visual evidence, deduplicated and
budgeted, with citations, produces grounded, traceable answers instead of hallucinations.

---

## 2. Previous Architecture (how context was assembled before)

Phase 2 (`app/context/`): `text chunks → duplicate detection → evidence ranking → compression →
context assembly → LLM`. Excellent and well-tested — but **text-only** and coupled to the retrieval
layer's `RetrievedChunk`. It could not represent, dedup, rank, budget, or cite a diagram, chart,
table, or image.

**Limitations:** no modality awareness; a fixed text-only layout; token budgeting over one stream;
compression tuned for prose; and citations that only pointed at text chunks. The multimodal evidence
Modules 1–3 produced had no path into the prompt.

---

## 3. New Architecture

```
   Multimodal Retrieval (Module 3 — CONSUMED, not duplicated)
     │  text · OCR · images · diagrams · charts · tables · metadata
     ▼
   Cross-modal Duplicate Detection   (merge Text↔OCR, Text↔Caption; keep complementary)
     ▼
   Cross-modal Evidence Ranking      (weighted, explainable signals across modalities)
     ▼
   Adaptive Token Budget Manager     (allocate by query intent; hard ceiling)
     ▼
   Multimodal Compression            (caption/OCR/table/metadata; citation-preserving)
     ▼
   Adaptive Context Assembly         (intent-driven block ordering — NOT fixed)
     ▼
   Multimodal Prompt Builder         (System → Query → per-modality sections → Citations → Question)
     ▼
   LLM   +   full explanation + observability
```

Phase-2 stays untouched; this is a parallel, modality-aware engine reusing Phase-2's tokenizer and
Module-3's intent/retrieval. Every stage is a modular, pure function; a new modality plugs in with no
pipeline change.

---

## 4. Context Pipeline

- **Cross-modal duplicate detection** (`dedup.py`) — cluster by content Jaccard ≥ 0.82 *regardless of
  modality*, so a passage and the OCR of the same page (or a diagram and its caption) collapse into
  one item; the strongest is the representative, the rest recorded as `merged_from` with modalities
  unioned. Complementary (low-overlap) evidence is never removed.
- **Cross-modal evidence ranking** (`ranking.py`) — a weighted blend of relevance, retrieval score,
  reranker score, modality importance (intent weight), vision/OCR confidence, citation quality,
  information density, and a multimodal-corroboration bonus. Each signal's weighted contribution is
  recorded (explainability).
- **Adaptive token budgeting** (`budget.py`) — split the window across modalities by intent weight,
  greedily fill by evidence score, compress to fit, redistribute leftover budget; the total is a hard
  ceiling never exceeded.
- **Multimodal compression** (`compression.py`) — OCR cleanup + keyword-dense sentence trimming for
  text/OCR, table summarization, metadata pruning; changes only `content`, never the citation.
- **Adaptive assembly** (`assembly.py`) — order blocks by intent (primary modality first), text kept
  high as the backbone; each modality becomes a labelled `ContextBlock`.
- **Prompt builder** (`prompt.py`) — deterministic structured prompt with `[n]` markers and a
  citation block.
- **Citation preservation** (`citations.py`) — every modality → a viewer target (document + page, +
  `asset_id` for visuals), deduplicated by target.
- **Developer inspection** — the `/build` response carries every score, reason, budget, and (in
  developer mode) the raw prompt.

---

## 5. Backend Architecture

Layered like every domain (`backend/app/mmcontext/`):

- **`models.py`** — `ContextBuildLog` (observability).
- **`schemas.py`** — `MMEvidence` / `ContextBlock` + API DTOs.
- **`dedup.py` / `ranking.py` / `budget.py` / `compression.py` / `assembly.py` / `prompt.py` /
  `citations.py`** — the modular, pure pipeline stages.
- **`repository.py`** — `ContextBuildLog` writes + observability aggregation.
- **`service.py`** — the **orchestrator**: consumes Module-3 search, runs the pipeline, logs, returns
  the full response.
- **`api.py`** — authenticated routes under `/workspaces/{id}/context`.

**Orchestrator** consumes `MultimodalRetrievalService.search()` (rerank + explain on) so it inherits
every retrieval signal — it never re-retrieves. **Caching:** the pipeline is stateless; a single
`ContextBuildLog` insert per build (observability). **Validation** rejects bad modalities/budgets;
**error handling** maps typed errors → HTTP; a failing stage degrades gracefully. **Metrics** are
computed per build and aggregated by the observability endpoint.

---

## 6. Prompt Engineering Strategy

- **Prompt structure:** System Instructions (answer only from evidence; visual evidence is
  authoritative; cite with `[n]`) → Question → per-modality evidence sections (each item `[n]`-tagged)
  → a Citation block (`[n]` → source label) → the User Question. Deterministic and easy to diff.
- **Adaptive layouts:** block order comes from assembly, driven by query intent — an architecture
  question leads with the diagram; a definition leads with text. There is **no fixed ordering**.
- **Context prioritization:** cross-modal ranking decides *what*; budgeting decides *how much*;
  compression decides *how condensed*.
- **Token allocation:** proportional to intent weights, then greedily filled, then redistributed —
  visual questions get more image/diagram budget, technical ones more text.
- **Modality balancing:** dedup removes cross-modal redundancy; the multimodal-corroboration bonus
  slightly favours evidence confirmed by multiple modalities.
- **Explainability:** every included item carries its evidence score, per-signal ranking
  contributions, selection reason, compression status, token cost, and merge lineage.

---

## 7. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/context.ts`** — the build + observability client.
- **`pages/ContextInspector.tsx`** (route `/workspace/:id/context`) — a **developer context
  inspector**: enter a query and see the detected intent + weights; a **metrics row** (retrieved →
  dedup → included → dropped, context tokens, dup-reduction %, compression %, latency); a **token
  budget** bar per modality (used/allocated); the **adaptive context blocks** with per-evidence cards
  (rank, score, tokens, compressed/merged tags, selection reason, and an expandable **ranking-signal
  breakdown**); the **citations**; and the **raw assembled prompt**. Evidence cards open the source
  document at its page (reuses Module 3 navigation).

**State management:** the page owns query/result state with an AbortController-guarded build.
**Routing:** nested under the workspace with a "🧠 Context" entry point. Theme-aware, responsive; the
per-signal bars + prompt viewer make the whole engine inspectable.

---

## 8. Future Integration

- **AI Agents** — a single `build(query)` that returns a budgeted, cited, explained multimodal prompt
  is the context-assembly tool an agent needs; the observability + explanation feed agent self-checks.
- **Knowledge Graph** — dedup merge lineage + citation targets are cross-modal edges.
- **Cross-document Reasoning** — assembly already spans a workspace's documents; multi-document
  multimodal context is one build.
- **Enterprise AI** — the modular stages + `ContextBuildLog` metrics + hard token ceiling are the
  substrate for governed, observable, large-context deployments.
- **Research Automation / Autonomous Workflows** — deterministic, inspectable prompts + explainable
  selection make multi-step automated research auditable.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}/context`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/build` | **Build context** (context preview + evidence ranking + compression report + token budget + explanation) | 200 `ContextResponse` | 422 |
| POST | `/prompt` | Developer prompt preview (forces developer mode) | 200 `{prompt, context, metrics, citations}` | 422 |
| GET | `/observability` | Aggregate build metrics (Phase-9) | 200 `ObservabilityResponse` | |

**`/build` request:** `{query, modalities?, document_id?, top_k, token_budget?, compress, dedup,
explain, developer}`.

**`/build` response:** `{primary_intent, modalities, weights, blocks:[{modality, header, order,
token_cost, items:[{content, evidence_score, token_cost, compressed, rank, selection_reason,
contributing_modalities, ranking_contributions, merged_from}]}], citations:[{modality, document_id,
page_number, asset_id, …}], budget:[{modality, allocated, used}], metrics:{retrieved, after_dedup,
included, dropped, context_tokens, prompt_tokens, duplicate_reduction, compression_ratio, total_ms,
stage_ms}, dropped:[{key, modality, reason}], prompt?, context?}`.

**Validation/errors:** `token_budget` ∈ [256, 32000]; `top_k` ∈ [1, 100]; unknown modality → 422;
foreign workspace → 404; `developer=false` omits the raw prompt.

---

## 10. Performance Optimizations

- **Consume, don't re-retrieve** — the orchestrator reuses Module-3's already-computed retrieval +
  rerank + explanation (no duplicated search).
- **Pure, staged pipeline** — each stage is O(n) over a bounded candidate set; timings are measured
  per stage (`stage_ms`).
- **Dedup before budget/compress** — merging cross-modal duplicates shrinks the set the expensive
  stages operate on.
- **Compress-to-fit, not drop** — evidence is condensed toward its remaining allocation before being
  dropped, maximizing information per token.
- **Hard token ceiling** — the total budget is enforced at every insertion (never exceeded), so
  prompts always fit the window.
- **Reused tokenizer** — Phase-2's heuristic counter (no re-embedding, no torch).
- **Single-insert observability** — the only hot-path write is one `ContextBuildLog` row.
- **Large-context scaling** — adaptive per-modality allocation keeps any one modality from starving
  the others as the window grows.

---

## 11. Testing

**Unit tests** (`test_mmcontext_unit.py`, 13) — each stage: cross-modal dedup (merges Text↔OCR, keeps
complementary), ranking (blends signals, sums to the score, modality-importance boost), budgeting
(hard ceiling, compress-to-fit, intent-weighted allocation), compression (table summarize, OCR
cleanup), adaptive assembly (primary-first ordering), deterministic + cited prompt, and citation
target dedup.

**Integration tests** (`test_mmcontext_api.py`, 8) — the full pipeline over HTTP:

```
Upload → Module-1 process → Module-2 vision → Module-3 retrieval (consumed) → Module-4 assembly
(dedup → rank → budget → compress → assemble → prompt → citations) → response
```

Covers auth/scoping (401/404), a diagram query assembling the diagram block **first** (adaptive) with
scores + reasons + ranking explanation + citations + metrics + budget, the **hard token ceiling**,
dedup-reduction + compression-ratio reporting, developer prompt preview (`/build` + `/prompt`),
modality scoping, observability aggregation, and an empty workspace.

**Results:** 21 new tests pass. Full suite: **409 passed** (only `test_reranker`/`test_eval` skipped —
they need torch/sentence-transformers, a pre-existing constraint; the mmcontext domain imports with no
faiss/torch/LLM). **No regressions** in Phase 1/2, Phase 3, or Phase 4 Modules 1–3. Frontend `tsc -b`
+ `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/mmcontext/__init__.py` — package doc.
- `app/mmcontext/models.py` — `ContextBuildLog`.
- `app/mmcontext/schemas.py` — `MMEvidence`/`ContextBlock` + DTOs.
- `app/mmcontext/dedup.py` — cross-modal duplicate detection.
- `app/mmcontext/ranking.py` — cross-modal evidence ranking.
- `app/mmcontext/budget.py` — adaptive token budget manager.
- `app/mmcontext/compression.py` — multimodal compression.
- `app/mmcontext/assembly.py` — adaptive context assembly.
- `app/mmcontext/prompt.py` — multimodal prompt builder.
- `app/mmcontext/citations.py` — cross-modal citation manager.
- `app/mmcontext/repository.py` — observability writes/aggregation.
- `app/mmcontext/service.py` — the orchestrator.
- `app/mmcontext/api.py` — the context router.
- `app/mmcontext/errors.py` — domain errors.
- `tests/test_mmcontext_{unit,api}.py` — 21 tests.

### New frontend files
- `src/api/context.ts`, `src/pages/ContextInspector.tsx`, `src/styles/context.css`.

### Modified files (why)
- `app/db/base.py` — register `ContextBuildLog` in `init_db()`.
- `app/main.py` — mount the context router.
- `tests/conftest.py` — import the model + mount the router (text retriever already overridden by M3).
- `src/App.tsx` — add the `/context` route.
- `src/types.ts` — add the context contracts.
- `src/main.tsx` — import `styles/context.css`.
- `src/pages/WorkspaceDetail.tsx` — add the "🧠 Context" entry point.

---

## 13. Lessons Learned

**Architecture decisions**
- *A parallel engine, not a Phase-2 rewrite.* Phase-2 is text-only and coupled to `RetrievedChunk`;
  building a modality-aware engine beside it (reusing only the tokenizer) kept Phase-1/2 tests green
  and let the multimodal pipeline evolve freely.
- *Consume retrieval, don't duplicate it.* The orchestrator runs Module-3 search and inherits every
  signal (fusion, rerank, contributions) — one source of truth, no re-retrieval.
- *Every stage is a pure function.* Dedup/ranking/budget/compression/assembly/prompt are pure and
  independently unit-testable without faiss/torch/LLM — which is why the whole engine is provable.
- *Explainability threaded through the object.* `MMEvidence` accumulates scores, reasons, budget, and
  merge lineage stage by stage, so the final response is a complete, inspectable audit trail.
- *Adaptive assembly is the core value.* Ordering blocks by query intent (not a fixed layout) is what
  makes a diagram lead an architecture answer — the single most impactful behaviour.

**Tradeoffs**
- *Lexical dedup/compression.* Duplicate detection uses token-set Jaccard and compression uses
  keyword-dense sentence selection — deterministic and dependency-free, but not semantic. An
  embedding-based dedup/compressor is the upgrade (the interfaces are unchanged).
- *Heuristic ranking weights.* The signal weights are hand-tuned, not learned; the contribution
  accounting makes them easy to calibrate later from `ContextBuildLog`.
- *Prompt is text-only today.* Visual evidence enters as its caption/structured description, not as an
  actual image token — correct for text LLMs; native image tokens plug into the prompt builder when a
  vision-LLM backend lands.

**Known limitations**
- No true vision-token prompts yet; lexical (not semantic) dedup/compression; ranking weights are
  static; the assembled context isn't yet wired into the live Chat/Summary generation path (the
  engine is exposed as an inspectable service — wiring it into generation is the natural next step).

**Future improvements**
- Wire the multimodal context into Chat/Summaries generation; embedding-based dedup + semantic
  compression; learned ranking weights from `ContextBuildLog`; native multimodal (image-token) prompts
  for vision-LLMs; per-query context caching; and Phase-9 context-quality dashboards.

---

### Success criteria — status

✅ Codebase audited · ✅ Multimodal Context Engine · ✅ Cross-modal duplicate detection · ✅ Cross-modal
evidence ranking · ✅ Adaptive token budgeting · ✅ Multimodal compression · ✅ Adaptive context
assembly · ✅ Multimodal prompt builder · ✅ Citation preservation extended · ✅ Developer context
inspector · ✅ Performance optimized · ✅ Observability · ✅ Tests passing (21 new, 409 total) · ✅ No
regressions in Phase 1/2 + Phase 3 + Phase 4 M1–3 · ✅ Documentation complete (this file).
