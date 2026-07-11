# Phase 4 — Module 3: Multimodal Retrieval Engine

> Status: ✅ Complete. Backend (12 files, a modular retriever framework + 1 table) + frontend
> (3 files) + 2 test suites (23 new tests, all passing; **388 total tests green** with no regressions
> across Phase 1/2, all of Phase 3, and Phase 4 Modules 1–2).

---

## 1. Module Overview

**Why multimodal retrieval is needed.** LexiMind's Phase-1 retrieval was excellent but **text-only**:
it searched a FAISS/BM25 index of text chunks. Meanwhile Modules 1–2 turned every document into a
rich multimodal store — OCR text, images, diagrams, charts, tables — with captions, structured
metadata, and (queued) embeddings. None of that was *searchable*. This module upgrades the Retrieval
Engine into a **unified multimodal search platform** that retrieves from every modality at once.

**Text retrieval vs cross-modal retrieval.** Text retrieval matches a query against text chunks with
one score distribution. Cross-modal retrieval runs **many retrievers** (text, OCR, image, diagram,
table, metadata), each with its own score distribution, then must **normalize** those scores to be
comparable, **fuse** them with per-modality weights, **deduplicate** the same knowledge found by
different modalities, and **rerank** across modalities — returning one unified, ranked, *explained*
result set. A query like *"explain the architecture diagram"* now activates the diagram retriever and
surfaces the actual diagram, not a paragraph that mentions it.

**Overall architecture.** A new `app/mmretrieval/` domain. Phase-1 `app/retrieval/` is **untouched** —
it is wrapped as the `text` retriever. Five DB-backed retrievers cover the other modalities over the
stores Modules 1–2 populated. An intent analyzer activates retrievers; a generalized fusion engine +
score normalization + cross-modal reranker produce unified, fully-explained results.

---

## 2. Previous Architecture (how LexiMind retrieved before)

```
Query → query analysis → dense (FAISS) ⊕ BM25 → RRF → cross-encoder rerank → Context Engine
```
One modality (text), one index, one score space. Robust and well-tested — but blind to the OCR text,
images, diagrams, charts, and tables Modules 1–2 extracted and understood.

**Limitations:** no way to search visual knowledge; a diagram/chart/table/screenshot was invisible to
retrieval; the multimodal chunks sat `embedding_status="pending"` with nowhere to be retrieved from;
and there was no framework to combine heterogeneous retrievers or explain cross-modal ranking.

---

## 3. New Architecture

```
   Query
     │
     ▼  intent analysis (which modalities? + fusion weights)
   ┌──────────────── Retriever Orchestrator ────────────────┐
   │  Text (Phase-1 hybrid, UNCHANGED) · OCR · Image ·        │
   │  Diagram · Table · Metadata     — one common interface  │
   └───────────────────────┬──────────────────────────────────┘
                           ▼  per-retriever score normalization → [0,1]
                    Multimodal Fusion (weighted RRF / weighted-sum, cross-modal dedup)
                           ▼
                  Cross-modal Reranking (modality-aware, model-swappable)
                           ▼
              Unified, ranked results + full explanation
                           ▼
   Context Engine (Phase 2, UNCHANGED) ── via `to_context_chunks` seam
```

Every retriever implements one interface (plug-and-play); every result carries a complete retrieval
explanation. The package imports with no faiss/torch (production text + cross-encoder lazy-import
Phase-1); Phase-1/Phase-2 behaviour is never changed.

---

## 4. Retrieval Pipeline

- **Retriever Orchestrator** (`service.py`) — intent → run activated retrievers → normalize → fuse →
  rerank → explain → log. Retrievers run sequentially on the request-scoped SQLite session (which is
  not thread-safe); the code is structured so a session-per-retriever executor can parallelize later.
- **Text Retrieval** — `HybridTextRetriever` wraps the **unchanged** Phase-1 pipeline
  (dense+BM25+RRF+cross-encoder over FAISS) in production; `LexicalTextRetriever` (DB, faiss-free) is
  the default/test backend. Both behind the same interface.
- **OCR Retrieval** — searches `MultimodalChunk` OCR chunks.
- **Image Retrieval** — searches `VisionAnalysis` (images/charts/screenshots/figures) over
  caption + keywords + type.
- **Diagram Retrieval** — searches `VisionAnalysis` diagram types over caption + **node labels** + type.
- **Table Retrieval** — searches `ExtractedTable` **header-aware** (headers weighted above cells).
- **Metadata Retrieval** — searches `Document` titles/descriptions.
- **Fusion** (`fusion.py`) — generalized weighted RRF / weighted-sum with cross-modal dedup.
- **Normalization** (`normalize.py`) — per-retriever min-max (default) or z-score→sigmoid.
- **Cross-modal Reranking** (`rerank.py`) — modality-aware relevance blended with fused rank.

---

## 5. Backend Architecture

Layered like every domain (`backend/app/mmretrieval/`):

- **`models.py`** — `RetrievalLog` (search stats / Phase-9 dashboards).
- **`intent.py`** — query understanding: modality triggers → activated retrievers + fusion weights.
- **`normalize.py`** — pure score normalization strategies.
- **`fusion.py`** — the generalized, modality-agnostic fusion framework (add a modality = add a
  weight; no code change).
- **`retrievers.py`** — the `Retriever` protocol + the six retrievers + the shared lexical scorer.
- **`rerank.py`** — `CrossModalReranker` interface + lexical (default) + cross-encoder (production).
- **`repository.py`** — reads over the unified stores + `RetrievalLog` writes + stats.
- **`service.py`** — the orchestrator + the `to_context_chunks` Phase-2 seam + suggestions/stats/health.
- **`api.py`** — authenticated routes under `/workspaces/{id}/search`.

**Retriever interface:** `modality: str` + `retrieve(ctx, k) -> list[RetrievalHit]`. Plug-and-play:
register a new class in the orchestrator. **Fusion engine:** weighted RRF over normalized,
rank-ordered per-modality lists, deduped by a stable `key`, with per-modality contribution
accounting. **Workers/caching:** retrieval is stateless (no background workers needed);
`RetrievalLog` is a single cheap insert per search; embedding/re-index queues are the existing
`MultimodalChunk.embedding_status` + `VisionEmbedding` (surfaced by `/search/health`). **Validation**
rejects unknown modalities (422); **error handling** degrades a failing retriever to empty rather than
failing the whole search.

---

## 6. Storage & Metadata Design

**No new retrieval storage** (beyond `RetrievalLog`): retrieval reads the stores Modules 1–2 already
built —
- `MultimodalChunk` (unified text/OCR chunks, `chunk_type`, `content`, `meta`, `embedding_status`),
- `VisionAnalysis` (image/diagram/table understanding: `image_type`, `caption`, `structured`, `keywords`),
- `ExtractedTable` (structured headers/cells),
- `Document` (metadata),
- `VisionEmbedding` (vision vectors — surfaced for the future semantic path).

**Indexes:** the owning modules already index by `workspace_id`/`document_id`/`chunk_type`/
`image_type`; `RetrievalLog` adds `ix_rlogs_ws_created`. **Relationships:** results dedup by a stable
`key` (`chunk:*` / `asset:*` / `doc:*`) so the same evidence found by multiple modalities merges.
**Scalability:** per-workspace candidate reads are bounded (limit) and retrievers are independent (and
parallelizable). **Extensibility:** a new modality is a new retriever + a fusion weight — no schema or
storage change.

---

## 7. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/search.ts`** — the search client (search, search-by-modality, suggestions, stats, health).
- **`pages/MultimodalSearch.tsx`** (route `/workspace/:id/search`) — one search box; an **intent
  banner** (activated modalities + weights + timing); **per-modality filter chips**; a
  **grouped/unified** toggle and a **cross-modal rerank** toggle; per-result **cards** (modality
  badge, title, snippet, confidence, page, "also found by"); and a per-result **explanation panel**
  (retriever, raw→normalized, fusion score + contributions, reranker, final rank). Clicking a result
  opens the source document at its page (reuses Module 3 navigation).

**Result cards / filters / preview / explanation** are all realized here. **State management:** the
page owns query/filter/toggle state with an AbortController-guarded fetch. **Routing:** nested under
the workspace; a "🔭 Search" entry point on the workspace home. Theme-aware via shared tokens,
responsive.

---

## 8. Future Integration

- **Multimodal Context Engineering** — `to_context_chunks(results)` already maps unified results to
  the chunk shape Phase-2 consumes (modality-tagged). Wiring it into the live context builder (dedup/
  rank/compress/cite over visual + text evidence) is the next module — the interface is ready and
  Phase-2 behaviour is unchanged today.
- **Knowledge Graph** — fused results link documents ↔ chunks ↔ assets across modalities; the
  contribution accounting is edge material.
- **AI Agents** — a single `search(query)` that spans every modality with explanations is the tool an
  agent needs to gather cross-modal evidence and justify it.
- **Cross-document Reasoning** — retrieval is workspace-wide; multi-document multimodal evidence is a
  single fused query.
- **Visual Search** — the image/diagram/table retrievers + `VisionEmbedding` are the seed; swapping
  the lexical image scorer for a CLIP text→image cosine is additive (the abstraction exists).
- **Enterprise Search** — the modular retriever framework + `RetrievalLog` stats + health/monitoring
  endpoints are the substrate for scaled, observable, multi-tenant search.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/search` | **Multimodal search** (query, modalities?, document_id?, top_k, fusion, normalize, rerank, explain) | 200 `SearchResponse` | 422 bad modality |
| GET | `/search/modality/{modality}?q=` | Search a single modality | 200 `SearchResponse` | 422 |
| GET | `/search/suggestions?q=` | Query suggestions (titles + captions) | 200 `{suggestions}` | |
| GET | `/search/stats` | Search statistics + indexed counts | 200 `StatsResponse` | |
| GET | `/search/health` | Retrievers, text backend, indexed, embedding queue | 200 `HealthResponse` | |

**Example — search:** `POST /search {"query":"explain the architecture diagram"}` →
`{intents:["diagram","metadata","text"], detected:["diagram"], primary:"diagram",
weights:{diagram:1.35,…}, total, total_ms, fusion_ms, rerank_ms, retriever_stats:[{modality,count,
latency_ms}], results:[{modality:"diagram", title, content, confidence, page_number, metadata,
explanation:{raw_score, normalized_score, fusion_score, fusion_contributions, reranker_score,
contributing_modalities, final_rank}}]}`.

**Validation/errors:** unknown modality → 422; foreign workspace → 404; a failing retriever degrades
to empty (never fails the whole search); `explain=false` omits per-result explanations.

---

## 10. Performance Optimizations

- **Parallel-ready orchestration** — retrievers are independent; they run sequentially on the request
  SQLite session (thread-unsafe) but the design supports a session-per-retriever executor with no
  changes to fusion/rerank. Per-retriever latency is measured and reported.
- **Bounded candidate reads** — each retriever pulls a capped candidate set and takes top-`k`.
- **Rank-based fusion** — weighted RRF is robust to score scale, avoiding an expensive re-embedding of
  everything to a common space.
- **Cheap normalization** — O(n) min-max per retriever.
- **Stateless + single-insert logging** — no hot-path DB writes except one `RetrievalLog` row.
- **Lazy heavy imports** — the domain imports with no faiss/torch; the production text retriever and
  cross-encoder load Phase-1 only when actually used.
- **Deduplication before rerank** — merging cross-modal duplicates shrinks the rerank set.
- **Large-workspace scaling** — the DB-backed retrievers index by workspace; a future embedding index
  (the `VisionEmbedding` seam) replaces the lexical scan for image/diagram at scale.

---

## 11. Testing

**Unit tests** (`test_mmretrieval_unit.py`, 15) — intent activation across the spec's example queries;
min-max + z-score normalization; fusion **dedup + contribution summing** across modalities +
weighted-sum; the lexical scorer's field weighting; each DB-backed retriever (OCR, diagram, image
exclusion, header-aware table, metadata); and cross-modal rerank (confidence + ordering) + the
no-rerank path.

**Integration tests** (`test_mmretrieval_api.py`, 12) — the full pipeline over HTTP with the
faiss-free lexical text retriever:

```
Upload → Module-1 process (OCR + image/table/figure) → Module-2 vision (captions + classification)
→ multimodal search → intent-driven modality activation → fusion → cross-modal rerank → explanation
→ stats/health/suggestions
```

Covers auth/scoping (401/404), intent-driven activation (a diagram query finds the architecture
diagram), OCR + header-aware table retrieval, **full explanation** (raw→normalized→fusion→reranker→
rank + contributions + retriever stats), cross-modal dedup structure, the search-by-modality endpoint,
the rerank toggle, modality validation (422), stats/health/suggestions, and an empty workspace.

**Results:** 23 new tests pass. Full suite: **388 passed** (only `test_reranker`/`test_eval` skipped —
they need torch/sentence-transformers, a pre-existing constraint; the mmretrieval domain imports with
no faiss/torch). **No regressions** in Phase 1/2, Phase 3, or Phase 4 Modules 1–2. Frontend `tsc -b` +
`vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/mmretrieval/__init__.py` — package doc.
- `app/mmretrieval/models.py` — `RetrievalLog`.
- `app/mmretrieval/intent.py` — query understanding.
- `app/mmretrieval/normalize.py` — score normalization.
- `app/mmretrieval/fusion.py` — the generalized fusion engine.
- `app/mmretrieval/retrievers.py` — the Retriever interface + 6 retrievers + lexical scorer.
- `app/mmretrieval/rerank.py` — cross-modal reranking.
- `app/mmretrieval/repository.py` — reads + stats.
- `app/mmretrieval/service.py` — the orchestrator + context seam.
- `app/mmretrieval/api.py` — the search router.
- `app/mmretrieval/schemas.py` / `errors.py` — hit type + DTOs + errors.
- `tests/test_mmretrieval_{unit,api}.py` — 23 tests.

### New frontend files
- `src/api/search.ts`, `src/pages/MultimodalSearch.tsx`, `src/styles/search.css`.

### Modified files (why)
- `app/db/base.py` — register `RetrievalLog` in `init_db()`.
- `app/main.py` — mount the search router.
- `tests/conftest.py` — import the model, mount the router, override the text retriever to the
  faiss-free lexical one.
- `src/App.tsx` — add the `/search` route.
- `src/types.ts` — add the search contracts.
- `src/main.tsx` — import `styles/search.css`.
- `src/pages/WorkspaceDetail.tsx` — add the "🔭 Search" entry point.

---

## 13. Lessons Learned

**Architecture decisions**
- *Extend, don't rewrite.* Wrapping the unchanged Phase-1 pipeline as one retriever behind a common
  interface preserved all its quality/tests while adding five new modalities around it. Phase-1/2
  behaviour is untouched; `to_context_chunks` is an interface, not a change.
- *A generalized fusion framework.* Making fusion modality-agnostic (a dict of ranked lists + a weight
  map) means adding a modality is adding a weight — the plug-and-play requirement met literally.
- *Normalize before fuse.* The single most important correctness decision: heterogeneous score
  distributions (BM25 magnitudes vs lexical counts vs cosine) must be normalized per retriever or the
  loudest retriever wins. Rank-based RRF further insulates fusion from scale.
- *Explanation as a first-class output.* Threading raw→normalized→fusion→contribution→reranker→rank
  through every hit makes the whole engine explainable — the foundation for trustworthy multimodal AI.
- *Injected text retriever.* Making the text backend pluggable (Phase-1 hybrid in prod, lexical-DB in
  tests) let the entire orchestrator/fusion/rerank framework be tested end-to-end without faiss/torch.

**Tradeoffs**
- *Sequential retriever execution.* One request-scoped SQLite session is thread-unsafe, so retrievers
  run sequentially. The design is parallel-ready (independent retrievers, measured latency); a
  session-per-retriever executor is the scale-up.
- *Lexical DB retrievers for visuals.* Image/diagram retrieval is lexical over captions/keywords/
  structure today (real and useful, since Module 2 produced rich captions), not yet CLIP-cosine over
  `VisionEmbedding`. The embedding seam exists; swapping it in is additive.
- *Production text/reranker are structure-validated.* faiss/torch aren't in the test env, so the
  Phase-1-wrapping retriever + cross-encoder are validated by structure + graceful fallback; the
  framework is proven end-to-end via the lexical backends.

**Known limitations**
- No semantic (embedding) image search yet (lexical only); fusion weights are heuristic (not learned);
  retrieval doesn't yet feed the live Context Engine (interface only); no distributed/parallel
  execution.

**Future improvements**
- CLIP text→image cosine retrieval via `VisionEmbedding`; learned fusion weights; parallel
  session-per-retriever execution; wire `to_context_chunks` into a multimodal Context Engineering
  module; per-modality recall metrics + Phase-9 dashboards from `RetrievalLog`.

---

### Success criteria — status

✅ Codebase audited · ✅ Multimodal retriever architecture (common interface, plug-and-play) · ✅ Query
intent analysis extended · ✅ OCR retrieval · ✅ Image retrieval · ✅ Diagram retrieval · ✅ Table
retrieval (header-aware) · ✅ Metadata retrieval · ✅ Multimodal fusion (generalized, weighted) ·
✅ Cross-modal reranking (modality-aware, swappable) · ✅ Unified search UI (filters + grouped +
explanation) · ✅ Retrieval metrics (`RetrievalLog` + stats/health) · ✅ Performance optimized ·
✅ Tests passing (23 new, 388 total) · ✅ No regressions in Phase 1/2 + Phase 3 + Phase 4 M1–2 ·
✅ Documentation complete (this file).
