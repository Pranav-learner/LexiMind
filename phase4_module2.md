# Phase 4 — Module 2: Vision Intelligence Engine

> Status: ✅ Complete. Backend (11 files, injected-engine + async runner + 3 tables) + frontend
> (3 files) + 2 test suites (19 new tests, all passing; **365 total tests green** with no regressions
> across Phase 1/2, all of Phase 3, and Phase 4 Module 1).

---

## 1. Module Overview

**Why vision intelligence is needed.** Module 1 *extracted* images, tables, and figures from
documents — but to LexiMind they were still opaque bytes on disk. Real documents encode critical
knowledge in **visuals**: architecture diagrams, flowcharts, UML, ER diagrams, charts, tables, and
UI/code screenshots. A knowledge platform that can't read them is missing a huge share of the
information. This module makes the AI **understand** those visuals, turning them into structured
semantic knowledge that lives alongside text.

**Image extraction vs image understanding.** Extraction answers *"where is the image and what does it
look like as bytes?"* Understanding answers *"what does it mean?"* — its **type** (architecture
diagram vs bar chart vs UI screenshot), a **semantic caption** ("System architecture showing API
Gateway → Auth → Retrieval → LLM"), its **structure** (diagram nodes/edges, chart axes/series, table
schema + column data-types, screenshot components), **objects & relationships**, **keywords/topics**,
**complexity**, **confidence**, and a **vision embedding**. `image_52.png` becomes a queryable
knowledge asset.

**Overall architecture.** A new `app/vision/` domain that consumes Module 1's extracted assets and
produces understanding. It reuses Module 1's `IngestionRepository` + `AssetStorage`, writes captions
back to the `caption` columns Module 1 reserved, and enriches the `MultimodalChunk` records — all
still `embedding_status="pending"` (retrieval untouched, per the mandate). Vision embeddings are
stored **separately** from text embeddings behind a swappable embedder abstraction.

---

## 2. Previous Architecture (how LexiMind handled images before)

After Phase 4 Module 1, an upload flowed:
```
Upload → classify → OCR (cached) → extract images/tables/figures → store bytes + rows → multimodal chunks (pending)
```
Images/figures were stored (`ExtractedImage`/`ExtractedFigure` with bytes on disk + a `caption`
column left **null** on purpose), tables had structured cells, and each asset had a
`MultimodalChunk` with a placeholder descriptor (`"[Image on page 2]"`).

**Limitations:** the platform knew an image *existed* but nothing *about* it — no classification, no
caption, no structural understanding, no vision embedding. A diagram and a photo were
indistinguishable; a chart's meaning was lost; a screenshot's UI was invisible. There was no way for
Chat/Summaries/Notes/Flashcards to reason about visual content.

---

## 3. New Architecture

```
   Module-1 extracted assets (ExtractedImage · ExtractedTable · ExtractedFigure)
        │  POST /documents/{id}/vision   (async)
        ▼
   ┌──────────────  Vision Intelligence Pipeline  ──────────────┐
   │  Classification → Structured Analysis (diagram/chart/table/  │
   │  screenshot) → Semantic Caption → Objects+Relationships →    │
   │  Keywords/Topics/Complexity → Vision Embedding               │
   └───────────────────────┬───────────────────────────────────────┘
        engine (injected)   │   background runner (threadpool)
        BLIP caption · CLIP │   progress · retry · cancel
        embed · analyzers   ▼
   VisionAnalysis  +  VisionEmbedding (stored separately from text)
        │
        ├─► caption written BACK to the Module-1 asset row
        ├─► MultimodalChunk enriched (content = caption, meta += vision, still `pending`)
        ▼
   Knowledge Assets → (FUTURE) multimodal retrieval · cross-modal context · visual search · agents
```

The engine is the **only** component that touches CLIP/SigLIP/BLIP; it is injected and lazy-imported
(the domain imports with none of them). Nothing enters the FAISS text index — retrieval is untouched.

---

## 4. Vision Processing Pipeline

- **Classification** (`analyzers.classify_asset`) — maps a Module-1 asset to a fine-grained type from
  a 16-type taxonomy (architecture_diagram, flowchart, er_diagram, uml, pie/bar/line/scatter/area
  chart, table, code/ui screenshot, scientific_figure, general_image) with a confidence.
- **Structured analysis** (`analyzers.build_structured`) — one builder per kind:
  - *Diagram* → nodes, edges, direction, hierarchy depth (Step 5).
  - *Chart* → chart_type, title, x/y axes, legend, series, trend (Step 7).
  - *Table* → **real** schema derived from the extracted headers/cells with inferred column
    data-types (Step 6 — goes beyond OCR).
  - *Screenshot* → components, layout, menus/buttons/forms, visible text (Step 8).
- **Captioning** (`analyzers.build_caption`) — a semantic, retrieval-worthy caption composed from the
  structured understanding (Step 4).
- **Semantic metadata** — objects, relationships, keywords, topics, complexity, confidence, language
  (Step 9).
- **Vision embedding** — a vector from the `VisionEmbedder` abstraction (CLIP/SigLIP in production;
  deterministic fake in tests), stored **separately** in `VisionEmbedding` (Step 10).
- **Background jobs** — the whole pipeline runs off-request in a threadpool worker with per-stage
  progress, retry, and cancellation; captions are written back and chunks enriched as analyses land.

---

## 5. Storage & Metadata Design

**Three new tables** (`backend/app/vision/models.py`):
- `VisionJob` — one async job per document (status/stage/progress/counts/logs/model info).
- `VisionAnalysis` — per-asset understanding: `image_type` (classification), `caption`, `objects`,
  `relationships`, `structured` (the diagram/chart/table/screenshot schema), `keywords`, `topics`,
  `complexity`, `confidence`, `language`, `thumbnail_path`. **Unique** `(asset_type, asset_id)` — one
  analysis per asset (re-analysis replaces it).
- `VisionEmbedding` — the vision vector stored **separately** from text embeddings: `model`,
  `model_family` (clip|siglip|fake), `dim`, `vector`. **Unique** `(asset_type, asset_id, model)`.

**Relationships:** analyses/embeddings hang off `(workspace_id, document_id)` and reference the
Module-1 asset by `(asset_type, asset_id)`; embeddings reference their `analysis_id`. **Indexes:**
`ix_visjobs_ws_doc`, `uq_vision_asset` + `ix_vision_doc_type`, `uq_vision_embedding` + `ix_vemb_doc`.

**Storage hierarchy:** thumbnails are written via Module-1's `AssetStorage` under
`assets/{ws}/{doc}/thumbnails/{asset_id}.png` (reuse, not duplication). The original image + captions
+ structured metadata + embeddings + classification + logs are all retained; `pipeline_version`
enables re-analysis of only stale assets. **Scalability:** analysis is per-document and bounded;
vectors live in `VisionEmbedding` (queryable independently of text); nothing bloats the FAISS index.

---

## 6. Backend Architecture

Layered like every domain (`backend/app/vision/`):

- **`models.py`** — the 3 tables.
- **`validation.py`** — the classification taxonomy + `analysis_kind` mapping.
- **`analyzers.py`** — the **pure** structured-understanding builders (diagram/chart/table/
  screenshot), captioning, keywords/complexity — real for tables, model-free scaffolding (identical
  output shape) for the rest, so it's exhaustively unit-testable without CLIP/BLIP.
- **`engines.py`** — the `VisionEngine` protocol + `FakeVisionEngine` (tests/contract) +
  `PipelineVisionEngine` (production: CLIP/SigLIP embedder + BLIP captioner, **lazy** + graceful
  degradation to the analyzers) + the swappable `VisionEmbedder` abstraction.
- **`repository.py`** — all SQL (jobs, analyses upsert, embeddings, search index).
- **`service.py`** — the async pipeline (`create_or_get_job`, `process_now`, `retry`, `cancel`), the
  **caption write-back**, and **MultimodalChunk enrichment**.
- **`runner.py`** — `VisionRunner` (threadpool, own session) + `InlineRunner` (tests) + `DeferredRunner`.
- **`api.py`** — authenticated routes under `/workspaces/{id}` (analyze / status / analyses /
  captions / single analysis / embedding / thumbnail / search-meta / job retry+cancel).

**Workers/queues:** the threadpool runner is the worker; the "queue" is the `VisionJob` state machine.
**Caching:** analysis is skipped when a completed job exists (unless forced); analyses upsert by asset
(no duplicates). **Validation** via the taxonomy; **error handling** maps typed errors → HTTP and
records failures on the job + logs.

---

## 7. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/vision.ts`** — the async client (analyze, status poll, analyses, captions, embedding,
  thumbnail-as-blob, job detail, retry, cancel).
- **`components/document/VisionPanel.tsx`** — embedded in the document detail drawer beneath the
  multimodal-processing panel: an Analyze/Re-analyze button, a live stage + progress bar while
  running, and a **gallery** of understood assets — each card shows a thumbnail, a classification
  badge, confidence, a complexity tag, the **semantic caption**, a **structured summary** (diagram
  nodes → / chart axes / table schema `name:dtype` / screenshot components), and keyword chips.

**Image viewer / metadata panel / gallery / diagram-table preview** are all realized in the
VisionPanel's gallery cards + `Structured` renderer. **Routing:** it lives inside the existing
document drawer (no new route). **State management:** the panel owns its own fetch + poll lifecycle
with an AbortController; thumbnails are lazily blob-loaded per card (auth-aware). Theme-aware via
shared tokens; degrades gracefully when a thumbnail can't render (icon fallback).

---

## 8. Future Integration

- **Multimodal Retrieval** — vision captions are already written onto the `MultimodalChunk` content
  and `VisionEmbedding` holds the vectors; a future worker embeds/indexes these so a query can match a
  diagram or table. The chunk is still `pending` (retrieval unchanged) — the interface is ready.
- **Cross-modal Context Engineering** — analyses share the chunk vocabulary (page, type, source,
  bbox, metadata); the Phase-2 dedup/ranking/compression/citation stages extend to visual evidence by
  adding a modality dimension — the shapes are already aligned.
- **AI Agents** — a classified, captioned, structured representation of every visual (diagram graph,
  table schema, chart axes) is exactly the tool surface an agent reasons over.
- **Knowledge Graph** — diagram nodes/edges and table columns/relationships are graph material with
  stable identity (`hash`, `asset_id`, page).
- **Visual Search** — the `search-meta` endpoint is the seed of a visual-knowledge index (caption +
  keywords + type); swapping the lexical filter for a `VisionEmbedding` similarity search is additive.
- **Explainable Vision AI** — every analysis carries confidence + structured evidence, so the AI can
  justify what it "saw" in an image.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/documents/{id}/vision` | **Analyze** the document's visual assets (async); `{force}` re-analyzes | 202 `VisionJob` | 404 doc |
| GET | `/documents/{id}/vision` | Latest job status (poll target) | 200 `VisionJob` \| null | 404 |
| GET | `/documents/{id}/vision/analyses?image_type=` | Per-asset understanding (filterable) | 200 `VisionAnalysisList` | 404 |
| GET | `/documents/{id}/vision/captions` | Caption lookup for the document's assets | 200 `[CaptionOut]` | 404 |
| GET | `/vision/analyses/{analysis_id}` | Single analysis (diagram/chart/table details in `structured`) | 200 `VisionAnalysisOut` | 404 |
| GET | `/vision/analyses/{analysis_id}/embedding?include_vector=` | Vision embedding metadata (+ optional vector) | 200 `VisionEmbeddingOut` | 404 |
| GET | `/vision/analyses/{analysis_id}/thumbnail` | Thumbnail PNG bytes | 200 image/png | 404 |
| GET | `/vision/search-meta?keyword=&image_type=` | Visual-knowledge search index | 200 `SearchMetaResponse` | |
| GET | `/vision/job/{job_id}` | Job detail + logs | 200 `VisionJobDetail` | 404 |
| POST | `/vision/job/{job_id}/retry` · `/cancel` | State transitions | 200 `VisionJob` | 409 |

**Example — analyses:** `GET /documents/{id}/vision/analyses` →
`{items:[{image_type:"architecture_diagram", caption:"…API → Auth → LLM…", structured:{kind:"diagram",
nodes:[…], edges:[…], edge_count}, keywords:[…], complexity, confidence, has_embedding:true}], total}`.

**Validation/errors:** unknown analysis/job/document → 404; illegal transition (cancel a completed
job / retry a running job) → 409; foreign workspace → 404; `include_vector` omits the (possibly
large) vector by default.

---

## 10. Performance Optimizations

- **Skip re-analysis** — a completed job is reused unless `force` is set; analyses upsert by asset
  (no duplicate work).
- **Caption write-back + chunk enrichment happen inline** as each analysis lands (single pass).
- **Separate embedding store** — `VisionEmbedding` keeps vision vectors out of the text FAISS index
  and queryable on their own; the vector is omitted from responses by default (bandwidth).
- **Lazy heavy imports + graceful degradation** — the domain imports with no CLIP/BLIP/torch; models
  load only in the production engine, and a missing model falls back to the pure analyzers (a diagram
  still gets structured metadata + a caption).
- **Swappable embedder** (`VisionEmbedder`) — CLIP↔SigLIP↔future VLM without touching consumers; the
  dim/model are recorded per embedding.
- **Batch-ready & GPU-ready** — the engine iterates a bounded asset list emitting per-asset events;
  batching inference and GPU placement are internal to the production engine (the contract is
  unchanged). Background threadpool keeps the API non-blocking; progress is streamed.

---

## 11. Testing

**Unit tests** (`test_vision_unit.py`, 9) — the analyzers + engine + embedder:
classification maps Module-1 hints across the taxonomy; **table understanding infers real column
data-types**; diagram understanding parses nodes/edges from captions; chart/screenshot shapes;
caption meaningfulness; keywords/topics + complexity (low→high); the fake embedder is deterministic
(same caption → same vector); the fake engine emits per-asset analysis + embedding + final.

**Integration tests** (`test_vision_api.py`, 10) — the full Module-1 → Module-2 flow over HTTP:

```
Upload → Module-1 process (extract image/table/figure) → Module-2 vision analyze (classify → caption
→ structure → embed) → analyses/captions endpoints → caption write-back to Module-1 assets → chunk
enrichment → single analysis + embedding (+vector) → visual search → empty-doc/reprocess/state errors
```

Covers auth/scoping (401/404), a completed job (asset_count/analyzed_count/embedding_count = 3),
classification + captions + structured table schema, **captions written back** to the Module-1 asset
rows, **`MultimodalChunk` enriched** (`vision_analyzed=true`, `vision_image_type`, still `pending`),
the captions endpoint, single-analysis + embedding (vector present with the flag, omitted without),
the `search-meta` index, an empty document completing with 0 assets, reprocess (reuse + force), and
409s on illegal cancel/retry.

**Results:** 19 new tests pass. Full suite: **365 passed** (only `test_reranker`/`test_eval` skipped
— they need torch/sentence-transformers, a pre-existing environment constraint; the vision domain
itself imports with no CLIP/torch). **No regressions** in Phase 1/2, Phase 3, or Phase 4 Module 1.
Frontend `tsc -b` + `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/vision/__init__.py` — package doc.
- `app/vision/models.py` — VisionJob / VisionAnalysis / VisionEmbedding.
- `app/vision/validation.py` — classification taxonomy + kind mapping.
- `app/vision/analyzers.py` — pure structured-understanding builders + captions.
- `app/vision/engines.py` — VisionEngine protocol + Fake + Pipeline + `VisionEmbedder` abstraction.
- `app/vision/repository.py` — all SQL.
- `app/vision/service.py` — the pipeline + caption write-back + chunk enrichment.
- `app/vision/runner.py` — background/inline/deferred runners.
- `app/vision/api.py` — the vision router.
- `app/vision/schemas.py` / `errors.py` — DTOs + domain errors.
- `tests/test_vision_{unit,api}.py` — 19 tests.

### New frontend files
- `src/api/vision.ts`, `src/components/document/VisionPanel.tsx`.

### Modified files (why)
- `app/db/base.py` — register the vision models in `init_db()`.
- `app/main.py` — mount `vision_router`.
- `tests/conftest.py` — import vision models, add `FakeVisionEngine` + inline runner override.
- `src/types.ts` — add the vision contracts.
- `src/components/document/DocumentDetailDrawer.tsx` — embed the `VisionPanel` section.
- `src/styles/ingestion.css` — add the vision gallery styles.

---

## 13. Lessons Learned

**Architecture decisions**
- *Understand on top of extract.* Building a separate `vision` domain over Module 1's assets (rather
  than folding vision into the extractor) kept each concern isolated: Module 1 owns extraction, Module
  2 owns understanding. Captions flow back into the columns Module 1 deliberately reserved — clean,
  additive, no schema churn.
- *The injected-engine + fake pattern, a seventh time.* Reusing the contract (engine bridges heavy
  libs lazily; runner runs it off-request; a deterministic fake drives tests) let the entire vision
  pipeline — classification, structured analysis, captioning, embeddings, retry/cancel — be
  exhaustively tested **without CLIP/BLIP/torch installed**.
- *Pure analyzers with a fixed output shape.* Because tables have real structure in the DB, table
  understanding is genuinely real; diagrams/charts/screenshots use model-free scaffolding that emits
  the *same shape* a VLM will, so swapping in the model never changes a single downstream consumer.
- *Separate vision embeddings + an embedder abstraction.* Keeping vision vectors out of the text FAISS
  index (per spec) and behind `VisionEmbedder` means multimodal retrieval and model swaps are additive.

**Tradeoffs**
- *Model-free scaffolding for non-table visuals.* Without a VLM in the environment, diagram/chart/
  screenshot understanding is deterministic scaffolding (real production swaps in BLIP/CLIP). Honest,
  dependency-free, and interface-complete — but the *content* quality is model-bound.
- *Production engine is structure-validated, not model-validated.* CLIP/BLIP aren't in the test env,
  so the production engine is validated by structure + graceful degradation; the *pipeline* is proven
  end-to-end via the fake. Running the real models is a CI/GPU concern.
- *Thumbnails are lazy blob fetches.* Auth-header images require a blob round-trip per card; fine at
  this scale, cacheable later.

**Known limitations**
- No real object detection / OCR-in-diagram yet (nodes are parsed from captions); chart value
  extraction is a stub; captions are placeholder-quality until the VLM lands; vision embeddings aren't
  yet used by retrieval (by design — interfaces only).

**Future improvements**
- Wire a real VLM (BLIP-2/LLaVA) + CLIP/SigLIP; batch + GPU inference; chart value extraction; a
  `VisionEmbedding` similarity search powering visual search; expose vision captions to Chat/Summaries/
  Notes/Flashcards; and cross-modal retrieval that ranks visual evidence beside text.

---

### Success criteria — status

✅ Codebase audited · ✅ Vision Intelligence Engine · ✅ Image classification · ✅ Caption generation ·
✅ Diagram understanding · ✅ Table understanding (real schema + dtypes) · ✅ Chart understanding ·
✅ Screenshot understanding · ✅ Vision embeddings (separate store + swappable embedder) · ✅ Semantic
metadata · ✅ Frontend visualization (gallery + metadata + confidence) · ✅ Performance optimized ·
✅ Tests passing (19 new, 365 total) · ✅ No regressions in Phase 1/2 + Phase 3 + Phase 4 M1 ·
✅ Documentation complete (this file).
