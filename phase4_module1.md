# Phase 4 — Module 1: Multimodal Document Processing Engine

> Status: ✅ Complete. Backend (11 files, injected-engine + async runner + 7 tables) + frontend
> (4 files) + 2 test suites (17 new tests, all passing; **346 total tests green** with no regressions
> across Phase 1/2 and all of Phase 3).

---

## 1. Module Overview

**Why multimodal ingestion is needed.** Through Phase 3, LexiMind understood only **text** — it
extracted text from native PDFs, chunked it, embedded it, and retrieved it. But real knowledge lives
in scanned documents, photographed whiteboards, screenshots, diagrams, charts, and tables. A
text-only pipeline is blind to all of it. This module is the beginning of LexiMind's evolution into a
**true multimodal knowledge system**: it converts *any* uploaded file into structured multimodal
knowledge.

**How it differs from text-only ingestion.** Text ingestion is a single linear path
(extract→chunk→embed). Multimodal ingestion is a **classified, staged pipeline**: detect the file
type, decide whether OCR is needed, run OCR (with caching), extract embedded images / tables /
figures, and generate **unified multimodal chunks** (text | ocr | image | table | figure) with rich
metadata — all asynchronously, with progress, retry, cancellation, and resumability.

**Overall architecture.** A **separate async processing layer attached to existing `Document` rows**.
It does not modify the Phase-1 text→retrieval path (zero regression, retrieval untouched) and it
does not embed anything yet — multimodal chunks land in a **future embedding queue**
(`embedding_status="pending"`). This module is the *ingestion foundation* for every future multimodal
capability (vision-language models, cross-modal retrieval, agents).

---

## 2. Previous Architecture (how LexiMind processed documents before)

```
Upload → validate → extract text (native PDF) → semantic chunk (embeddings) → FAISS + BM25 → retrieval
```

Everything was **text-only and synchronous-ish**: `ingest_pdf` pulled text with a PDF text
extractor, `chunk_text` grouped paragraphs semantically, and chunks went straight into the vector
store. The `Document` row already carried forward-looking fields (`media_type`, `ocr_status`,
free-form `processing_status`/`processing_stage`) in anticipation of this module.

**Limitations:** scanned PDFs and images yielded little or no text (no OCR); embedded images, tables,
and figures were discarded; there was no document classification, no per-asset metadata, no
extraction pipeline, and no background job system for heavy processing. LexiMind could read a text
PDF but was blind to a photograph of the same page.

---

## 3. New Architecture

```
   Upload (existing text path: extract → chunk → embed → retrieval — UNCHANGED)
        │
        ▼  POST /documents/{id}/process   (async, attached to the Document)
   ┌──────────────  Multimodal Processing Pipeline  ──────────────┐
   │  Validation → Classification → OCR (cached) → Extraction      │
   │      (images · tables · figures) → Multimodal Chunking →      │
   │      Metadata → Embedding Queue (pending) → Completed         │
   └───────────────────────┬───────────────────────────────────────┘
        engine (injected)   │   background runner (threadpool)
        PyMuPDF · PaddleOCR │   progress · retry · cancel · resume
        pdfplumber          ▼
   ProcessingJob · OcrResult · ExtractedImage/Table/Figure · MultimodalChunk · ProcessingLog
        │
        ▼  (FUTURE) multimodal embeddings → cross-modal retrieval
```

The engine is the **only** component that touches OCR/vision/PDF libraries; it is injected and
lazy-imported (the domain imports with none of them). Text retrieval is never modified.

---

## 4. Processing Pipeline

Implemented in `service.process_now` (consumes the injected engine's event stream) — the stages:

- **Validation** — the file type is checked against a supported-format registry (415 otherwise).
- **Classification** — `text_pdf` (native), `scanned_pdf` (ocr), `mixed_pdf` (mixed), or
  `image`/`screenshot`/`photo` (image_only). Production probes PDF text density via PyMuPDF; images
  are OCR-only. Stored on the job for future modules.
- **OCR** — per page, **cache-first**: the engine consults `OcrResult` (keyed by content hash) and
  only runs OCR (PaddleOCR primary → Tesseract fallback) on a miss, capturing text, confidence,
  language, bounding boxes, and reading order. Cached results are never recomputed.
- **Image extraction** — every embedded image with page, bbox, size, type, hash, stored file.
- **Table extraction** — detected tables with headers, rows, bbox (stored separately from text).
- **Figure extraction** — figures/diagrams/charts with type, caption, hash, bbox.
- **Multimodal chunking** — `chunking.build_multimodal_chunks` turns per-page text + assets into
  unified chunks (text | ocr | image | table | figure), each with page, type, source, bbox,
  metadata, and a searchable descriptor; `embedding_status="pending"`.
- **Metadata** — the job accumulates counts (pages/images/tables/figures/chunks), OCR confidence,
  language, processing time, and `pipeline_version`.
- **Progress tracking** — every stage emits a `{stage, progress}` event; `ProcessingLog` records a
  line per stage for observability.
- **Background jobs** — the whole thing runs off the request path in a threadpool worker; the API
  returns a `queued` job and the client polls.

---

## 5. Database & Storage Design

**Seven new tables** (`backend/app/ingestion/models.py`):
- `ProcessingJob` — the async job + classification + counters + progress (`file_hash` skips
  reprocessing unchanged files; `completed_stages`/`pipeline_version` support resume/versioning).
- `OcrResult` — per-page OCR **cache**, unique on `(document_id, page_number, content_hash)`.
- `ExtractedImage` / `ExtractedTable` / `ExtractedFigure` — extracted assets (page, bbox, metadata,
  hash, stored file path).
- `MultimodalChunk` — the unified chunk with `chunk_type`, `source`, bbox, content, and the
  **future embedding queue** (`embedding_status` + `embedding_model`, indexed).
- `ProcessingLog` — per-stage log lines.

**Relationships:** every table hangs off `(workspace_id, document_id)`; assets/chunks/logs also
carry `job_id`. **Indexes:** `ix_mmjobs_ws_doc`, `uq_ocr_cache` + `ix_ocr_doc`, `ix_mmchunks_doc_type`
+ `ix_mmchunks_embed`, plus `job_id`/`workspace_id` indexes.

**Storage hierarchy** (`storage.py`, local FS, swappable for object storage):
```
assets/{workspace_id}/{document_id}/
    images/{image_id}.{ext}   figures/{figure_id}.{ext}   tables/…   ocr/…
```
Writes are incremental (one file per asset) and idempotent by asset id.

**Scalability:** per-document processing is bounded; OCR caching + `file_hash` skip duplicate work;
assets stream to disk (not held in memory); the DB rows are lean (bytes live on the filesystem).

---

## 6. Backend Architecture

Layered like every domain (`backend/app/ingestion/`):

- **`models.py`** — the 7 tables.
- **`validation.py`** — the supported-format **registry** (`SUPPORTED_TYPES` now; `FUTURE_TYPES`
  declared for docx/pptx/epub/html) + validators — adding a format is a one-line change.
- **`storage.py`** — `AssetStorage`, the on-disk hierarchy (swappable interface).
- **`chunking.py`** — the pure multimodal chunk builder (lightweight word-window on the same
  250-word budget; the semantic text chunker is untouched → backward compatible).
- **`engines.py`** — `MultimodalEngine` protocol + `FakeMultimodalEngine` (tests/contract) +
  `PipelineMultimodalEngine` (production: PyMuPDF / PaddleOCR / Tesseract / pdfplumber, **lazy** +
  graceful degradation).
- **`repository.py`** — all SQL (jobs, OCR cache, assets, chunks, logs, counts).
- **`service.py`** — the staged pipeline (`create_or_get_job`, `process_now`, `retry`, `cancel`, +
  queries), OCR-cache orchestration, and the `Document.ocr_status` mirror.
- **`runner.py`** — `IngestionRunner` (threadpool, own session) + `InlineRunner` (tests) +
  `DeferredRunner`.
- **`api.py`** — authenticated routes under `/workspaces/{id}` (process / status / assets / ocr /
  chunks / job detail / retry / cancel).

**Workers & queues:** the threadpool runner is the worker; the "queue" is the `ProcessingJob.status`
state machine (queued→processing→completed/failed/cancelled). A dead-letter queue is future-ready
(`attempts` is tracked). **Caching:** OCR results by content hash; unchanged files (by `file_hash`)
skip reprocessing entirely. **Validation** rejects unsupported media (415); **error handling** maps
typed domain errors → HTTP and records failures on the job + logs (partial assets are kept).

---

## 7. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/ingestion.ts`** — the async client (process, status poll, assets, ocr, chunks, job detail,
  retry, cancel) + `pollProcessing`.
- **`components/document/ProcessingPanel.tsx`** — embedded in the document detail drawer: a
  Process/Reprocess button, a live **stage + progress bar** while running (polled to terminal), the
  classification chips, OCR / image / table / figure / chunk **counts**, an extracted-**asset viewer**
  (tables with headers, figures with captions, images with size/page), an OCR-text preview, collapsible
  **processing logs**, and **retry/cancel**.

**Upload/processing flow:** the existing multi-file upload is unchanged; multimodal processing is a
per-document action in the detail drawer. **Processing states** (queued/processing/completed/failed/
cancelled) each render distinctly. **Error handling:** failures show the job error + a Retry button.
**State management:** the panel owns its own fetch + poll lifecycle with an AbortController;
everything is theme-aware via shared tokens and responsive inside the drawer.

---

## 8. Future Integration

- **Vision Intelligence** — `ExtractedImage`/`ExtractedFigure` carry `caption` (nullable) + stored
  bytes; a vision-language model fills captions and image embeddings with no schema change.
- **Multimodal Retrieval** — `MultimodalChunk.embedding_status="pending"` is a ready embedding queue;
  a future worker embeds these chunks (text + image + table) into a (possibly separate) index. The
  chunk model already unifies modality, page, bbox, and source.
- **Cross-modal Context Engineering** — multimodal chunks share the chunk vocabulary (chunk_id, page,
  type, source, bbox, metadata) the Phase-2 engine consumes, so dedup/ranking/compression/citation
  extend to them by adding a modality dimension — the interfaces are already shaped.
- **Knowledge Graph** — extracted figures/tables + OCR entities are graph nodes; `hash`/bbox/page
  give stable identity and provenance.
- **AI Agents** — a classified, structured, per-asset representation of every document is exactly the
  tool surface an agent needs to reason across modalities.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/documents/{id}/process` | **Start** multimodal processing (async); `{force}` reprocesses | 202 `ProcessingJob` | 404 doc, 415 media |
| GET | `/documents/{id}/processing` | Latest job status (poll target) | 200 `ProcessingJob` \| null | 404 |
| GET | `/documents/{id}/assets` | Extracted images / tables / figures | 200 `AssetsResponse` | 404 |
| GET | `/documents/{id}/ocr` | OCR pages + language + avg confidence | 200 `OcrStatusResponse` | 404 |
| GET | `/documents/{id}/multimodal-chunks?chunk_type=` | Unified chunks (filterable) | 200 `[MultimodalChunk]` | 404 |
| GET | `/processing/{job_id}` | Job detail + processing logs | 200 `JobDetail` | 404 |
| POST | `/processing/{job_id}/retry` | Re-queue a failed/cancelled job | 200 `ProcessingJob` | 409 |
| POST | `/processing/{job_id}/cancel` | Cancel a queued/processing job | 200 `ProcessingJob` | 409 |

**Example — process:** `POST /documents/{id}/process {"force":false}` → `202 {id, status:"queued",
doc_type, processing_type, ...}`; poll `GET /documents/{id}/processing` until `completed` →
`{ocr_pages, image_count, table_count, figure_count, chunk_count, ocr_confidence, processing_ms}`.

**Validation/errors:** unsupported media → 415; missing document/job → 404; illegal transition
(cancel a completed job / retry a running job) → 409; foreign workspace → 404.

---

## 10. Performance Optimizations

- **OCR caching** — `OcrResult` keyed by content hash; a page is OCR'd once, ever. Reprocessing (even
  forced) reuses cached OCR (proven in tests).
- **Skip unchanged documents** — `create_or_get_job` returns the existing completed job when the
  `file_hash` is unchanged and not forced — no duplicate work.
- **Incremental storage** — assets stream to disk one file at a time (bounded memory); DB rows stay
  lean (bytes on the filesystem, not in the DB).
- **Background workers** — heavy OCR/vision runs off the request path in a threadpool; the API never
  blocks. Progress is streamed per stage.
- **Parallel extraction (ready)** — the event-stream engine contract lets a production engine emit
  page/asset events concurrently; the service persists as they arrive.
- **Lazy heavy imports** — the domain imports with no PaddleOCR/PyMuPDF/torch; models load only in
  the production engine at runtime (fast, offline-safe imports; test-substitutable).
- **Graceful degradation** — a missing extractor logs + yields nothing rather than failing the job.

---

## 11. Testing

**Unit tests** (`test_ingestion_unit.py`, 9) — validation (supported/future/unsupported types),
multimodal chunking (all chunk types, contiguous indices, table serialization, native vs OCR source,
word-window splitting), `AssetStorage` file writes, and the `FakeMultimodalEngine` honouring the OCR
cache + emitting the full event contract.

**Integration tests** (`test_ingestion_api.py`, 8) — the full pipeline over HTTP with the inline
runner + fake engine:

```
Upload → process → classification → OCR → image/table/figure extraction → multimodal chunking →
metadata → assets/ocr/chunks endpoints → job logs → reprocess (skip unchanged) → forced reprocess
(OCR served from cache) → retry/cancel state errors
```

Covers auth/scoping (401/404), missing-document 404, a completed job with all asset types + correct
counts (2 OCR pages, 1 image, 1 table, 1 figure, 5 chunks), the assets/ocr/chunks endpoints (+
`chunk_type` filter, `embedding_status="pending"`), job logs, **skip-unchanged** + **OCR-cache**
behaviour on reprocess, and 409s on illegal cancel/retry.

**Results:** 17 new tests pass. Full suite: **346 passed** (only `test_reranker`/`test_eval` skipped
— they need torch/sentence-transformers, a pre-existing environment constraint; the ingestion domain
itself imports with no OCR/vision libs). **No regressions** in Phase 1/2 or Phase 3. Frontend
`tsc -b` + `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/ingestion/__init__.py` — package doc.
- `app/ingestion/models.py` — the 7 ingestion tables.
- `app/ingestion/validation.py` — supported-format registry + validators.
- `app/ingestion/storage.py` — `AssetStorage` (on-disk hierarchy).
- `app/ingestion/chunking.py` — the multimodal chunk builder.
- `app/ingestion/engines.py` — `MultimodalEngine` protocol + Fake + Pipeline (lazy heavy libs).
- `app/ingestion/repository.py` — all SQL.
- `app/ingestion/service.py` — the staged pipeline + OCR-cache orchestration.
- `app/ingestion/runner.py` — background/inline/deferred runners.
- `app/ingestion/api.py` — the ingestion router.
- `app/ingestion/schemas.py` / `errors.py` — DTOs + domain errors.
- `tests/test_ingestion_{unit,api}.py` — 17 tests.

### New frontend files
- `src/api/ingestion.ts`, `src/components/document/ProcessingPanel.tsx`, `src/styles/ingestion.css`.

### Modified files (why)
- `app/db/base.py` — register the ingestion models in `init_db()`.
- `app/main.py` — mount `ingestion_router`.
- `tests/conftest.py` — import ingestion models, add `FakeMultimodalEngine` + inline runner override.
- `src/types.ts` — add the ingestion contracts.
- `src/main.tsx` — import `styles/ingestion.css`.
- `src/components/document/DocumentDetailDrawer.tsx` — embed the `ProcessingPanel` section.

---

## 13. Lessons Learned

**Architecture decisions**
- *A separate async layer, not a rewrite.* Attaching multimodal processing to existing `Document`
  rows (rather than rebuilding upload/ingest) meant **zero regression risk** to the text pipeline and
  retrieval, and satisfied the "prepare infrastructure, don't modify retrieval" mandate exactly.
- *The injected-engine + fake pattern, again.* Reusing the proven contract (engine bridges heavy libs
  lazily; runner runs it off-request; a deterministic fake drives tests) let the whole pipeline —
  classification, cached OCR, extraction, chunking, retry/cancel — be exhaustively tested **without
  PaddleOCR/PyMuPDF/torch installed**. This is the single most important decision.
- *Event-stream engine → persisting service.* The engine emits a typed event stream and the service
  owns persistence, progress, cancellation, and chunking. This keeps the heavy libs isolated and the
  business logic testable and DB-aware.
- *Embedding queue, not embedding.* Multimodal chunks land `pending` — Phase-1 retrieval is untouched
  and the future multimodal-embeddings module has a ready work queue.

**Tradeoffs**
- *Lightweight multimodal chunker.* The semantic (embedding-based) text chunker needs torch, so
  multimodal text uses a word-window splitter on the same budget. Honest and dependency-free; the two
  can unify once multimodal embeddings land.
- *Production OCR/extraction is unit-untested here.* PaddleOCR/PyMuPDF aren't in the test env, so the
  production engine is validated by structure + graceful-degradation, and the *pipeline* is validated
  end-to-end via the fake. Running the real engine is an environment/CI concern.
- *Threadpool, not a distributed queue.* Fine for a single process; a Celery/RQ backend (and a real
  dead-letter queue) drops in behind the same runner interface at scale.

**Known limitations**
- Table/figure detection quality depends on the production libraries (heuristic figure detection);
  captions are placeholders until Vision Intelligence lands; no image embeddings yet (by design).

**Future improvements**
- Multimodal embeddings + cross-modal retrieval; vision-language captioning; a distributed queue +
  dead-letter handling; DOCX/PPTX/EPUB/HTML support (registry-ready); and richer table structure
  (cell spans, CSV export).

---

### Success criteria — status

✅ Codebase audited · ✅ Multimodal ingestion · ✅ Document classification · ✅ OCR pipeline (cached) ·
✅ Image extraction · ✅ Table extraction · ✅ Figure extraction · ✅ Multimodal chunk generation ·
✅ Metadata system extended · ✅ Background processing (threadpool runner, retry/cancel/resume) ·
✅ Upload/processing UI (progress + counts + assets + logs) · ✅ Performance optimized (OCR cache,
skip-unchanged, lazy imports) · ✅ Tests passing (17 new, 346 total) · ✅ No regressions in Phase 1/2 +
Phase 3 · ✅ Documentation complete (this file).
