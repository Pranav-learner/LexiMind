# LexiMind — Phase 3 · Module 2: Document Library

> **Status:** ✅ Complete · **New backend tests:** 43/43 passing (99 in the light env, incl.
> the shared Phase-1/2 + Module-1 suites) · **Frontend:** builds clean (`tsc -b && vite build`) ·
> **Builds on:** [phase1.md](./phase1.md), [phase2.md](./phase2.md), [phase3_module1.md](./phase3_module1.md)
>
> The canonical reference for Phase 3, Module 2. A new engineer should understand the entire
> Document Library — backend domain, lifecycle, retrieval/context integration, and frontend —
> from this file alone.
>
> **One-line goal:** promote an uploaded file from an *implicit, filename-derived identity that
> lived only in FAISS metadata* into a **first-class, managed knowledge asset** inside a
> workspace — with a real lifecycle, rich metadata, search/filter, and full CRUD.

---

## Table of Contents
1. [Module Overview](#1-module-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Database Design](#4-database-design)
5. [Backend Architecture](#5-backend-architecture)
6. [Frontend Architecture](#6-frontend-architecture)
7. [Upload & Processing Pipeline](#7-upload--processing-pipeline)
8. [Retrieval Integration](#8-retrieval-integration)
9. [API Documentation](#9-api-documentation)
10. [Testing](#10-testing)
11. [File Changes Summary](#11-file-changes-summary)
12. [Future Compatibility](#12-future-compatibility)
13. [Lessons Learned](#13-lessons-learned)

---

## 1. Module Overview

### Why a Document Library is necessary
After Module 1, a workspace could *count* its documents (`Workspace.document_count`) but could
not **name, browse, inspect, or manage** them. A "document" was an implicit thing: a
filename-derived `document_id` (`doc_<sha1(filename)[:12]>`) written into every chunk's vector
metadata. There was:

- no way to **list** the files in a workspace,
- no **display name**, description, or per-document **status**,
- no **metadata** (pages, words, chunks, embedding model, language, sizes),
- no **rename / archive / delete / re-index**,
- no way to know whether a file **finished indexing** or **failed**,
- and no safe **cleanup** — deleting a file's chunks/embeddings was impossible.

The Document Library formalizes the document into a **relational entity** that bridges the
structured world (SQLite) and the vector world (FAISS/BM25), and becomes **the single source of
truth for every indexed document**.

### Product goals
- Every uploaded file is a **managed asset**: upload, browse, search, sort, filter, rename,
  archive/restore, delete (soft & permanent), re-index, and inspect.
- **Rich metadata** surfaced per document: pages, word count, chunk count, embedding model &
  dimension, language, upload date, last indexed, processing duration, storage size.
- **Observable lifecycle**: every stage (Uploaded → Text Extraction → Chunking → Embedding →
  FAISS → BM25 → Metadata → Ready) exposes progress and a status.
- **Safe, reversible operations**: soft-delete by default; permanent delete purges chunks,
  embeddings, FAISS entries, BM25 entries, and the physical file.
- **No regressions**: Phase-1/2 retrieval and Module-1 workspaces keep working unchanged.

### User workflow
```
Open a workspace  →  "📚 Open Document Library"  →  /workspace/:id/library
   ├─ Drag & drop PDFs (multi-file, per-file progress + retry)
   ├─ Watch each doc move Uploaded → … → Ready (live status badge + progress)
   ├─ Search / filter (type, language, indexed, archived) / sort / paginate
   ├─ Click a card → detail drawer (metadata, stats, index health, activity)
   └─ Rename · Archive/Restore · Re-index · Delete (soft) · Delete permanently
```

### Scope boundary (explicit)
Implemented: the full document domain + lifecycle + management UI for **PDF** documents. The
schema and layering are shaped for **future media types** (images, audio, video, web pages) and
**future AI metadata** (summaries, chat, flashcards) — those are **not** implemented here, by
design, but slot in without rewrites (`media_type`, free-form `*_status` columns, an extensible
detail drawer).

---

## 2. Previous Architecture

Before this module, an uploaded file left **no relational trace**. The `/upload/pdf` route:

```
POST /upload/pdf → save bytes to uploaded_pdfs/<filename>
                 → ingest_pdf(): extract → chunk → embed → FAISS add + JSON metadata
                 → (if workspace) Workspace.document_count += 1
```

| Concern | Before Module 2 |
|---|---|
| Document identity | implicit `document_id = doc_<sha1(filename)[:12]>` in chunk metadata only |
| Where a "document" lived | nowhere as a row — only as a repeated key across N chunk records |
| Metadata | none (no pages/words/chunks/model/language/size as structured data) |
| Status / progress | none — the request blocked until done, success or failure invisible afterward |
| Browse / search / manage | impossible — no list endpoint, no names, no CRUD |
| Rename / archive / delete | impossible — you could not remove a file's vectors/BM25 entries |
| Filename safety | `uploaded_pdfs/<filename>` written as-is (collision + traversal risk) |

### Limitations
1. **No management surface** — a workspace was a black box of vectors.
2. **No lifecycle observability** — you couldn't tell *processing* from *failed* from *ready*.
3. **No cleanup** — `IndexFlatL2` + a positional JSON list had no per-document delete, so files
   accumulated forever.
4. **No metadata** — nothing to sort/filter by, nothing to show a user, nothing for citations.
5. **Duplicate accumulation** — re-uploading the same filename appended a second copy of every
   chunk (same `document_id`), silently inflating the index.

> **A latent seam existed:** every chunk already carried a stable `document_id` and (after
> Module 1) a `workspace_id`. Module 2 completes that seam by giving `(document_id,
> workspace_id)` a **relational home** rather than inventing a new identifier.

---

## 3. New Architecture

### Where the Document sits
```
User (owner)
 └── Workspace (Module 1)
       └── Document (Module 2)  ← NEW first-class entity
             │  id, display_name, description, status, statistics, embedding provenance
             │  vector_document_id  ─────────────────────────────┐
             └── chunks in FAISS + vector_metadata.json ◄─────────┘  (linked by this string)
```

### Two stores, one link (unchanged philosophy from Module 1)
| Layer | Holds | Owned by |
|---|---|---|
| **SQLite** (`app/db`) | users, workspaces, **documents** | `app/auth`, `app/workspaces`, **`app/documents`** |
| **FAISS + JSON** | vectors + chunk metadata (incl. `document_id`, `workspace_id`) | `app/services`, `app/retrieval` |

The **only** bridge between a `Document` row and its vectors is the string
`Document.vector_document_id`, which equals every chunk's `metadata["document_id"]`. All
chunk-level operations (count / delete / re-index / health) filter chunk metadata by
`(vector_document_id, workspace_id)` — scoping by both so two workspaces that uploaded a
same-named file (hence the same derived id) never touch each other's chunks.

### End-to-end request flow (Module 2)
```
                    ┌──────────────── Browser (React + Router) ────────────────┐
  /workspace/:id ──▶│  WorkspaceDetail → "Open Document Library"                │
                    │  /workspace/:id/library → DocumentsLibrary                │
                    │     UploadDropzone · Toolbar · DocumentCard grid · Drawer │
                    └───────────────┬──────────────────────────────────────────┘
                                    │  Bearer token
                                    ▼
  ┌──────────────────────────────── FastAPI ─────────────────────────────────────────┐
  │  /workspaces/{id}/documents (auth, owner+workspace scoped)                          │
  │     POST      → DocumentService.create_pending → ingest(on_stage,replace) → complete│
  │     GET       → DocumentService.list (SQL search/filter/sort/paginate)              │
  │     GET /{id} → DocumentService.get + indexing.compute_index_health (FAISS/BM25)    │
  │     PATCH     → rename / edit description                                            │
  │     archive/restore/reindex/DELETE(?permanent)                                       │
  │  /query       → excludes archived+deleted docs' vector ids from retrieval            │
  └───────────────┬───────────────────────────────────────────────────────────────────┘
                  │
      ┌───────────┴───────────────┐
      ▼                           ▼
 SQLite (leximind.db)     FAISS + vector_metadata.json
 users, workspaces,       vectors + chunk metadata
 documents               (document_id, workspace_id)
```

### Clean-architecture package (mirrors Module 1 exactly)
`app/documents/` is a self-contained domain package where **business logic never lives in API
handlers, the API never issues SQL directly, and the package never imports faiss** (the vector
singletons are injected):

```
app/documents/
  models.py       Document ORM (status, statistics, vector link) + indexes
  schemas.py      Pydantic DTOs + list-query enums + status vocabularies
  validation.py   pure field/file validation + language/word helpers
  errors.py       transport-agnostic domain errors
  repository.py   all SQL (owner + workspace scoped, soft-delete aware, paginated)
  service.py      lifecycle rules (upload/process/rename/archive/delete, counters)
  indexing.py     the ONLY bridge to FAISS/BM25 (count/remove/health) — faiss injected
  api.py          thin authenticated HTTP routes under /workspaces/{id}/documents
```

---

## 4. Database Design

**Engine:** SQLite via SQLAlchemy 2.0 (same store as Module 1). No Alembic yet — the schema is
additive; `init_db()` now also registers `app.documents.models`.

### Table: `documents`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `doc_<uuid16>` |
| `workspace_id` | `String(40)` | **INDEX** — every list scopes by workspace |
| `owner_id` | `String(40)` | **INDEX** — owner scoping without a join |
| `vector_document_id` | `String(40)` | **INDEX** — link to chunk `metadata["document_id"]` |
| `filename` | `String(500)` | sanitized physical/original name |
| `display_name` | `String(500)` | user-facing, renamable |
| `description` | `Text` | default `""` |
| `media_type` | `String(20)` | `document` (future: image/audio/video/webpage) |
| `file_type` | `String(20)` | e.g. `pdf` |
| `mime_type` | `String(120)` | e.g. `application/pdf` |
| `file_size` | `Integer` | bytes |
| `storage_path` | `String(1000)` | `uploaded_pdfs/<ws>/<doc_id>__<name>` |
| `page_count` | `Integer` | derived |
| `word_count` | `Integer` | derived |
| `chunk_count` | `Integer` | derived |
| `language` | `String(20)` | heuristic (`en`/`unknown`) |
| `embedding_model` | `String(120)` | provenance (`all-MiniLM-L6-v2`) |
| `embedding_dimension` | `Integer` | provenance (`384`) |
| `processing_status` | `String(30)` **INDEX** | `uploaded\|processing\|ready\|failed` |
| `processing_stage` | `String(40)` | current pipeline stage |
| `processing_error` | `Text` NULL | last failure message |
| `processing_ms` | `Integer` NULL | processing duration |
| `upload_progress` | `Integer` | 0–100 (derived from stage) |
| `indexing_status` | `String(30)` | `pending\|indexed\|stale\|failed` |
| `summary_status` | `String(30)` | `none` (future AI) |
| `ocr_status` | `String(30)` | `none` (future OCR) |
| `is_archived` | `Boolean` **INDEX** | active/archived split |
| `deleted_at` | `DateTime(tz)` NULL | **soft-delete tombstone** (NULL = live) |
| `last_indexed_at` | `DateTime(tz)` NULL | |
| `created_at` / `updated_at` | `DateTime(tz)` | `updated_at` has `onupdate=now` |

### Indexes & why
| Index | Purpose |
|---|---|
| `documents.workspace_id` | every library list filters by workspace |
| `documents.owner_id` | owner scoping (defense in depth) |
| `documents.vector_document_id` | chunk-level ops resolve a document by its vector id |
| `documents.processing_status` | filter/telemetry on lifecycle state |
| `documents.is_archived` | active vs archived filter |
| `ix_documents_ws_filename` (`workspace_id`,`filename`) | duplicate-file detection + lookups |
| `ix_documents_ws_vector` (`workspace_id`,`vector_document_id`) | scoped chunk resolution |

### Relationships
`documents.workspace_id → workspaces.id` and `documents.owner_id → users.id` are **logical FKs**
(not hard DB constraints yet, consistent with Module 1's bootstrap-friendly stance). The
document↔chunk relationship is the **soft link** `vector_document_id == metadata["document_id"]`
— the FAISS layer stays intentionally decoupled from the relational schema.

### Scalability considerations
- Listing is two cheap queries (a `COUNT` + a windowed `SELECT … ORDER BY … LIMIT/OFFSET`) with
  an `id` tiebreak for stable pagination — no N+1, no full-table scans.
- Free-form status strings (not booleans/enums in the DB) mean a future OCR/summary/transcription
  stage needs **no migration** — just a new value.
- `media_type` + separate `file_type`/`mime_type` let non-PDF assets land later without schema
  changes; only a new extractor is required.
- Move to Postgres by env var (`LEXIMIND_DATABASE_URL`) exactly as in Module 1.

---

## 5. Backend Architecture

### Models (`models.py`)
The `Document` ORM (above), with the six indexes and two composite indexes. Designed for future
multimodal support via `media_type` and free-form status columns.

### Repositories (`repository.py`) — the only SQL
`DocumentRepository` is owner **and** workspace scoped and soft-delete aware. Key methods:
- `get` / `get_by_vector_id` (the Context-Engine accessor), `filename_exists` (case-insensitive,
  live rows only),
- `list(...)` — the whole listing in two queries with search (filename **or** display_name **or**
  description), archived filter, indexed filter, `file_type`/`language` filters, sort column via
  `getattr(Document, sort_by.value)`, `id` tiebreak,
- `list_excluded_vector_ids(workspace_id)` — vector ids of **archived OR soft-deleted** docs (for
  retrieval exclusion),
- writes: `create`, `save` (bumps `updated_at`), `soft_delete`, `hard_delete`.

### Services (`service.py`) — the only place lifecycle rules live
`DocumentService(repo, workspace_service=None)` owns:
- `create_pending` — validate display name/description, **duplicate-file guard**, create the row
  in `processing`/`uploaded` state (raises *before* any expensive work),
- `set_stage` — advance the stage and derive `upload_progress` from its position,
- `complete` — record statistics, flip to `ready`/`indexed`, set `last_indexed_at`, and bump the
  workspace `document_count` **once** (`count_as_new`; re-index passes `False`),
- `fail` — record the error and flip to `failed`,
- `update` (rename/description — **never** renames the physical file), `archive`/`restore`
  (state-transition guards → `DocumentStateError`), `mark_stale`,
- `delete(permanent=…)` — soft by default; decrements `document_count` exactly once for a
  counted (ready) document; returns the row so the route can purge chunks + the file.

Counter maintenance is **best-effort** (drift is non-fatal and never blocks a document op).

### Validation (`validation.py`) — pure, no I/O
`validate_display_name` (defaults to filename, collapses whitespace, length + forbidden/control
char checks), `validate_description`, `sanitize_filename` (strips path components → **prevents
`../` traversal** + forbidden chars, never empty), `validate_file_type` (against
`settings.supported_document_extensions` → `UnsupportedFileType`), `validate_file_size`
(`settings.max_upload_bytes` → `FileTooLarge`, rejects empty), plus `guess_language`,
`count_words`, `mime_for`, `normalize_name_for_compare`.

### Lifecycle bridge (`indexing.py`) — the only FAISS/BM25 touchpoint
Takes the `vector_store`/`bm25_retriever` singletons as **parameters** (injected by the route),
so the whole `documents` package stays faiss-free and light-env testable:
- `count_chunks`, `remove_document_chunks` (rebuild-based delete + `bm25.mark_dirty()` + persist),
- `compute_index_health(vector_store, bm25, document)` → `IndexHealth {chunk_count,
  embedding_count, faiss_status, bm25_status, index_health}`.

`VectorStore` gained two general helpers (all FAISS calls stay inside `vector_store.py`):
`count_where(predicate)` and `remove_where(predicate)` (reconstructs kept vectors into a fresh
`IndexFlatL2` and rewrites the positional metadata list).

### Error handling
Domain errors carry an HTTP `status_code` + machine `code` but import no web framework; `api.py`
maps them via a tiny `_handle` translator:

| Domain error | HTTP |
|---|---|
| `DocumentValidationError` | 422 |
| `UnsupportedFileType` | 415 |
| `FileTooLarge` | 413 |
| `DocumentNotFound` | 404 |
| `DuplicateDocument` | 409 |
| `DocumentStateError` | 409 |

### API layer (`api.py`) — thin, authenticated, faiss-lazy
Every route depends on `get_current_user_id` and verifies workspace ownership (`_verify_workspace`
→ 404). The heavy singletons and the ingestion function are pulled in through **lazy FastAPI
dependencies** (`get_index_context`, `get_ingestor`) that import `app.core.state` /
`ingestion_service` only when called — so `app.documents.api` imports with no faiss/torch and
**tests override those dependencies with in-memory fakes** to drive the full HTTP lifecycle.

---

## 6. Frontend Architecture

**Stack (unchanged):** React 19 + Vite 7 + `react-router-dom` v7 + a React auth Context + native
`fetch`. Plain global CSS with the `ws-*` design system, extended by a new `document.css`. Pages
are lazy-loaded. The base document type is named **`LibraryDocument`** in TypeScript to avoid
shadowing the DOM global `Document`.

### Pages & routing
| Route | Page | Purpose |
|---|---|---|
| `/workspace/:workspaceId` | `WorkspaceDetail` | now links to the library ("📚 Open Document Library") |
| `/workspace/:workspaceId/library` | `DocumentsLibrary` | the library dashboard (upload + browse + manage) |

`DocumentsLibrary` nests under the workspace context boundary Module 1 established, inheriting the
`workspace_id` scope, exactly as Module 1 promised future modules would.

### Components (`src/components/document/`)
| Component | Role |
|---|---|
| `DocumentCard` | **memoized** card: file-type icon, display name, filename, stat row (pages/chunks/words), embedding model, **color-coded status badge** (ready=green, processing=amber with stage + a `upload_progress` bar, failed=red), relative upload time, quick actions. Click → detail drawer. |
| `DocumentToolbar` | presentational: search, filters (archived/indexed/file_type/language), sort + order, **grid/list toggle**. Lifts all state up. |
| `UploadDropzone` | **drag & drop** + file picker, multi-file, **per-file progress bar** (XHR), success/error, **retry** for failed files. |
| `DocumentDetailDrawer` | right-side slide-in: General / Processing / Index / Embedding / Chunk statistics / Storage / Workspace / Recent Activity, plus a disabled **AI features** placeholder; hosts Rename/Archive/Reindex/Delete. |
| `constants.ts` | file-type → icon map + sort option list |

### State management
- **Page-local state** in `DocumentsLibrary` (matching Module 1's dashboard): `items/total/pages`,
  query controls (debounced 300ms `search`, `archived`, `indexed`, `file_type`, `language`,
  `sort_by`, `order`), `view` (grid/list), `page` (PAGE_SIZE=12), and `selected` (drawer).
- **`AbortController`** in a `useRef` cancels superseded fetches (no out-of-order state); page
  resets to 1 on any filter/sort/search change.
- No new global context — the library fetches its workspace locally by `:workspaceId`, matching
  the existing per-page convention.

### API layer (`src/api/documents.ts`)
`listDocuments`, `getDocument`, `updateDocument`, `archiveDocument`, `restoreDocument`,
`reindexDocument`, `deleteDocument` go through the shared `apiRequest` (token auto-attached);
`uploadDocument(ws, file, onProgress)` uses **`XMLHttpRequest`** (fetch can't report upload
progress) with the bearer token, one file per request for per-file progress + retry.

### UI structure (library dashboard)
```
┌───────────────────────────────────────────────────────────────┐
│ ← Machine Learning · Document Library        [ ⬆ Upload ] [▦/≣]│
│ [ 🔍 search… ] [Active|Archived|All] [Indexed▾] [Type▾] [Sort▾]│
│ ┌── drag & drop PDFs here (multi, progress, retry) ──┐         │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│ │📄 OS.pdf│ │📄 ML.pdf│ │📄 …     │ │📄 …     │  …cards…       │
│ │Pg 20 · Ch 42 · 12k words · MiniLM · ●Ready    │               │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘               │
│                    ← Prev   Page 1 of 3   Next →              │
└───────────────────────────────────────────────────────────────┘
   click a card → right-side Detail Drawer (metadata · stats · index · activity)
```

---

## 7. Upload & Processing Pipeline

```
Upload (drag & drop / picker, one request per file, XHR progress)
   ↓
Validation      sanitize filename · supported type (415) · size ≤ 50 MB (413) · empty (422)
   ↓
Create row      create_pending → duplicate-file guard (409) → status=processing, stage=uploaded
   ↓
Persist bytes   uploaded_pdfs/<workspace_id>/<doc_id>__<name>   (no cross-file overwrite)
   ↓
Extraction      on_stage("text_extraction")   pdfplumber → paragraphs
   ↓
Chunking        on_stage("chunking")           semantic chunk_text()
   ↓
Embedding       on_stage("embedding")          batched all-MiniLM-L6-v2 (384-d)
   ↓
FAISS Indexing  on_stage("faiss_indexing")     replace_existing=True (idempotent) → add vectors
   ↓
BM25 Indexing   on_stage("bm25_indexing")      mark corpus dirty (lazy rebuild)
   ↓
Metadata        on_stage("metadata")           word_count, language, sample_text
   ↓
Ready           complete(): stats + status=ready/indexed + last_indexed_at + document_count += 1
```

Each `on_stage(stage)` callback calls `DocumentService.set_stage`, which persists the stage and a
derived `upload_progress` (0→100 across the eight stages) so the UI shows **real** progress, not a
fake spinner. A failure at any stage calls `DocumentService.fail` (status=`failed`, error stored)
and reports the file as failed **without aborting the rest of the batch**. `replace_existing=True`
makes upload/re-index **idempotent** — re-uploading a filename replaces its chunks instead of
duplicating them.

---

## 8. Retrieval Integration

The Document Library layers on top of the Phase-1/2 pipeline **without rewriting it**.

### Every document exposes its index state
`GET /workspaces/{id}/documents/{doc}` returns `index_health`:

| Field | Meaning |
|---|---|
| `chunk_count` | live vector-metadata records for this doc `(vector_document_id, workspace_id)` |
| `embedding_count` | vectors attributable to this doc (one per chunk in an `IndexFlatL2`) |
| `faiss_status` | `indexed` / `missing` / `unknown` (consistency of `index.ntotal` vs metadata) |
| `bm25_status` | `indexed` / `missing` (BM25 draws from the same metadata, never drifts) |
| `index_health` | `healthy` / `degraded` / `empty` |

### Archived & deleted documents leave retrieval
"Archived documents should not appear in normal retrieval." Rather than mutate the vector store,
`/query` performs a cheap, indexed DB lookup (`list_excluded_vector_ids`) for the workspace's
**archived OR soft-deleted** documents and folds their ids into a **new negative filter facet**,
`RetrievalFilter.exclude_document_id`. A chunk whose `document_id` is excluded is dropped before
fusion/rerank. This is:
- **reversible** (restore/undelete simply stops excluding them — chunks were never touched),
- **backward compatible** (no `workspace_id` on the query → no exclusion → unchanged behavior),
- **covered** by the existing `test_filters.py`/`test_fusion.py` (still 11/11) plus new assertions.

### Permanent delete purges everything
Permanent delete calls `indexing.remove_document_chunks` → `VectorStore.remove_where` (rebuilds
FAISS excluding the doc's vectors), marks BM25 dirty (lazy rebuild on the smaller corpus), removes
the physical file, then hard-deletes the row and decrements `document_count`. Cleanup is
best-effort and ordered so the row is always removed even if the index step hiccups.

### No Phase-2 rewrite required
Because archived/deleted chunks are filtered **upstream at retrieval**, the Phase-2 context engine
(dedup → rank → budget → compress → assemble) automatically operates on the correct set with zero
changes — the same design dividend Module 1 earned.

### Context-Engine metadata accessor (Step 9)
`DocumentRepository.get_by_vector_id(workspace_id, vector_document_id)` /
`DocumentService.get_by_vector_id` resolve the rich `Document` row behind a retrieved chunk's
`document_id`. This is the seam a future citation-generator / context-assembler uses to enrich
output with display names, descriptions, page/word counts, and language — without coupling the
context package to the documents schema today.

---

## 9. API Documentation

All routes are under `POST/GET /workspaces/{workspace_id}/documents…` and require
`Authorization: Bearer <token>`; the caller must own the workspace (else 404).

### `POST /workspaces/{id}/documents` (multipart) → 201
Form field **`files`** (repeatable; the UI sends one file per request). Each file is validated,
persisted, and processed independently.
Response: `{ "uploaded": int, "failed": int, "items": [ { "filename", "success", "error",
"document": DocumentOut|null } ] }`.
Per-item errors: unsupported type (415-class message), too large (413-class), empty (422-class),
duplicate filename (409-class) — reported in `items[].error`, never aborting the batch.

### `GET /workspaces/{id}/documents` → 200
Query params: `page` (≥1), `page_size` (1–100), `search`, `archived` (`active|archived|all`),
`indexed` (`any|indexed|unindexed`), `file_type`, `language`,
`sort_by` (`display_name|created_at|file_size|page_count|last_indexed_at|updated_at`),
`order` (`asc|desc`).
Response: `{ items: DocumentOut[], total, page, page_size, pages }`.

### `GET /workspaces/{id}/documents/{doc}` → 200
Response: `DocumentDetail` = `DocumentOut` + `index_health: IndexHealth | null`. Errors: 404.

### `PATCH /workspaces/{id}/documents/{doc}` → 200
Body: `{ display_name?, description? }` (partial). Renames the **display name** only — the
physical file is never renamed. Response: `DocumentOut`. Errors: 422, 404.

### `POST …/{doc}/archive` → 200 · `POST …/{doc}/restore` → 200
Response: `DocumentOut`. Errors: 409 already-archived / not-archived · 404.

### `POST …/{doc}/reindex` → 200
Removes the doc's existing chunks and re-ingests from `storage_path` (idempotent); does **not**
re-count the workspace. Response: `DocumentOut`. Errors: 409 (source file unavailable) · 404.

### `DELETE …/{doc}?permanent=false` → 204
Soft-delete by default (reversible; chunks retained but excluded from retrieval).
`?permanent=true` purges chunks + embeddings + FAISS + BM25 + the physical file and hard-deletes
the row. Errors: 404.

### DTO — `DocumentOut`
`id, workspace_id, owner_id, vector_document_id, filename, display_name, description, media_type,
file_type, mime_type, file_size, page_count, word_count, chunk_count, language, embedding_model,
embedding_dimension, processing_status, processing_stage, processing_error, processing_ms,
upload_progress, indexing_status, summary_status, ocr_status, is_archived, last_indexed_at,
created_at, updated_at`.

### `/query` (unchanged shape, enhanced behavior)
Still `{ question, workspace_id?, filters?, top_k? }`. When `workspace_id` is supplied it now also
excludes that workspace's archived/deleted documents from retrieval. A request with no
`workspace_id` is completely unchanged.

---

## 10. Testing

**43 new backend tests**, all passing, on the same **in-memory SQLite (StaticPool)** + **minimal
FastAPI app** harness Module 1 uses — extended so the document router mounts with its heavy
dependencies (`get_index_context`, `get_ingestor`) overridden by **in-memory fakes**
(`FakeVectorStore`, `FakeBM25`, `make_fake_ingest`). No faiss/torch needed.

| File | Type | Covers |
|---|---|---|
| `test_document_validation.py` | unit | display-name default/collapse/length/forbidden/control, description cap, **filename sanitization (path traversal)**, extension/type (415), mime, size bounds (413/empty), language guess, word count, casefold compare (11) |
| `test_document_repository.py` | unit | owner scoping, case-insensitive `filename_exists` + free-after-soft-delete, soft-delete hides, pagination + total, search (filename/display/description), archived + indexed + type + language filters, sorting, **excluded-vector-ids covers archived+deleted**, `get_by_vector_id` (10) |
| `test_document_service.py` | unit | create defaults + duplicate guard, stage progression, complete stats + counter-once, **reindex doesn't re-count**, fail, rename (file untouched), archive/restore state machine, **soft-delete decrements only counted docs**, missing→404, owner scoping (12) |
| `test_document_api.py` | **integration** | auth-required 401, foreign-workspace 404, single upload processes→ready + chunks land + counter bump, multi-upload, per-item unsupported/duplicate failures, list search/sort/paginate, **details incl. index health**, rename, **archive hides + marks excluded**, **reindex replaces (not duplicates) chunks**, soft-then-permanent delete purges chunks + counter, and a **full lifecycle** create→get→list→rename→archive→restore→reindex→delete (10) |

### The required integration lifecycle
`test_full_lifecycle` drives the real HTTP surface end-to-end: upload (→ `ready`, 3 chunks in the
fake store) → get → list(total=1) → rename → archive → restore → reindex (chunks replaced, still
3) → permanent delete (204) → get → 404.

### Coverage & regression
- Every layer (validation, repository, service, api, indexing bridge) is covered; the integration
  test exercises the whole HTTP path with a realistic staged ingest.
- **No Phase-1/2/Module-1 regression.** The shared files touched (`retrieval/schemas.py`,
  `retrieval/filters.py`, `services/vector_store.py`, `services/ingestion_service.py`) keep their
  existing tests green, and the new negative facet defaults to inert (`exclude_document_id=None`
  keeps `is_empty()` true → empty filter matches everything).

```bash
# new + shared light suite (sqlalchemy + fastapi + pydantic + pytest + httpx + python-multipart)
cd backend && python -m pytest tests/test_document_*.py tests/test_workspace_*.py \
    tests/test_auth.py tests/test_filters.py tests/test_fusion.py -q      # 99 passed
# full suite (in the real backend venv with faiss/torch)
cd backend && ./venv/bin/python -m pytest tests/ -q
```

Frontend: `cd frontend/leximind-frontend && npm run build` (`tsc -b && vite build`) compiles
clean; the library page and its components ship as their own lazy chunk.

---

## 11. File Changes Summary

### New files — Backend
| File | Purpose |
|---|---|
| `app/documents/__init__.py` | package contract/docstring |
| `app/documents/models.py` | `Document` ORM + indexes (status, statistics, vector link) |
| `app/documents/schemas.py` | DTOs, list-query enums, status vocabularies, `IndexHealth`/`DocumentDetail` |
| `app/documents/validation.py` | pure field/file validation + filename sanitization + language/word helpers |
| `app/documents/errors.py` | transport-agnostic domain errors (404/409/413/415/422) |
| `app/documents/repository.py` | all SQL (owner+workspace scoped, soft-delete aware, listing, exclusion, vector lookup) |
| `app/documents/service.py` | lifecycle rules (create/stage/complete/fail, rename, archive/restore, delete, counters) |
| `app/documents/indexing.py` | the only FAISS/BM25 bridge (count/remove/health), faiss injected |
| `app/documents/api.py` | authenticated `/workspaces/{id}/documents` routes; lazy heavy deps |
| `tests/test_document_validation.py`, `test_document_repository.py`, `test_document_service.py`, `test_document_api.py` | 43 new tests |

### Modified files — Backend
| File | Reason |
|---|---|
| `app/core/config.py` | add `max_upload_bytes` (50 MB) + `supported_document_extensions` (`{pdf}`) |
| `app/db/base.py` | register `app.documents.models` in `init_db()` |
| `app/main.py` | mount the document router |
| `app/services/vector_store.py` | add `count_where` + `remove_where` (per-document delete via rebuild) |
| `app/services/ingestion_service.py` | add `on_stage` callback, `replace_existing` (idempotent), return `word_count`/`embedding_*`/`sample_text` |
| `app/api/query.py` | exclude archived/deleted docs' vector ids from retrieval |
| `app/retrieval/schemas.py` | add negative `exclude_document_id` facet to `RetrievalFilter` |
| `app/retrieval/filters.py` | allow the `exclude_document_id` request key |
| `tests/conftest.py` | in-memory index fakes + document router app + `workspace` fixture; temp upload dir |

### New files — Frontend
| File | Purpose |
|---|---|
| `src/api/documents.ts` | typed document API client (+ XHR upload with progress) |
| `src/components/document/constants.ts` | file-type icon map + sort options |
| `src/components/document/DocumentCard.tsx` | memoized document card (status badge + progress) |
| `src/components/document/DocumentToolbar.tsx` | search/filter/sort + grid/list toggle |
| `src/components/document/UploadDropzone.tsx` | drag & drop, multi-file, progress, retry |
| `src/components/document/DocumentDetailDrawer.tsx` | metadata/stats/index/activity drawer |
| `src/pages/DocumentsLibrary.tsx` | the library dashboard page |
| `src/styles/document.css` | drawer + dropzone + status/list styles (theme-aware) |

### Modified files — Frontend
| File | Reason |
|---|---|
| `src/types.ts` | add `LibraryDocument`, `IndexHealth`, list/params/upload-result types |
| `src/App.tsx` | add lazy `/workspace/:workspaceId/library` route |
| `src/pages/WorkspaceDetail.tsx` | link to the Document Library |
| `src/main.tsx` | import `styles/document.css` |

---

## 12. Future Compatibility

The Document Library is the substrate the remaining Phase-3 modules read from:

| Future capability | What Module 2 already provides |
|---|---|
| **PDF Viewer** | `storage_path` + `page_count`; the detail drawer is the natural mount point |
| **AI Chat** | per-document metadata accessor (`get_by_vector_id`) for citations; workspace-scoped retrieval already isolates + excludes archived |
| **Summaries** | `summary_status` column already present (`none`); the drawer has an AI-features placeholder to activate |
| **Notes / Flashcards** | documents are addressable entities to attach notes/cards to; counts flow through the workspace counters |
| **OCR** | `ocr_status` column + `media_type` distinction ready for image/scanned inputs |
| **Multimodal (image/audio/video/web)** | `media_type` + separate `file_type`/`mime_type` + free-form status columns → new extractor only, no migration |
| **Bulk actions / trash view** | soft-delete tombstone + status make a trash/restore surface a UI addition, not a schema change |

Every new capability follows the **same layering** (model → repository → service → api + DTOs +
validation + errors), reuses `get_current_user_id` for scoping, injects the vector singletons for
any index work, and extends the detail drawer rather than replacing it.

---

## 13. Lessons Learned

### Design decisions
- **Give the existing identity a home, don't mint a new one.** Chunks already carried
  `document_id` + `workspace_id`; Module 2 made `(document_id, workspace_id)` a relational row via
  `vector_document_id` instead of inventing a parallel key — so legacy chunks and new documents
  line up.
- **Keep faiss out of the domain package.** `app/documents` imports no faiss; the vector
  singletons and the ingestion function are **injected through lazy FastAPI dependencies**. This
  kept the module importable and the *entire* HTTP lifecycle testable in the light env with
  in-memory fakes — the single biggest testability win.
- **Exclude, don't mutate.** Archiving/soft-deleting a document filters its chunks out of
  retrieval via a negative facet computed from a cheap indexed query — reversible, and it left the
  Phase-2 context engine untouched.
- **Real, staged progress.** Threading an `on_stage` callback through `ingest_pdf` turned the
  opaque blocking upload into eight observable stages with a derived percentage.
- **Idempotent ingest.** `replace_existing=True` removes a document's prior chunks before adding
  new ones, so re-upload and re-index never inflate the index — fixing a latent duplication bug.

### Tradeoffs
- **Synchronous processing** (no job queue): simplest correct thing; the staged callbacks give
  progress within one request. A background worker + polling is the clean next step for large PDFs.
- **`IndexFlatL2` rebuild on delete**: O(n) reconstruct, fine at the current corpus scale; a
  future `IndexIDMap`/per-workspace shard removes the rebuild.
- **Service-enforced duplicate-file check**, not a partial unique index — clearer with
  soft-delete/archive, consistent with Module 1's name-uniqueness stance.
- **Heuristic language detection** (`en`/`unknown`) — zero-dependency and offline; swap in a real
  detector behind the same `guess_language` seam without touching the schema.
- **Best-effort counter maintenance** — a document operation never fails because a counter update
  did; a reconciliation job can true it up if drift is ever observed.

### Known limitations
- Logical (not hard) FKs from `documents.workspace_id`/`owner_id`, consistent with Module 1.
- Permanent delete's index cleanup and the row delete aren't a single transaction across the two
  stores; ordering favors always removing the row, with best-effort chunk/file purge.
- No pre-flight size rejection before the bytes are read (the whole file is read, then validated) —
  acceptable at 50 MB; streaming validation is a later refinement.
- Re-index requires the original file on disk (`storage_path`); a missing source returns 409.

### Future improvements
1. Background processing (queue + worker) with progress polling for large/slow documents.
2. `IndexIDMap` or per-workspace vector shards → O(1) deletes, no rebuild.
3. Real language detection, page-accurate word counts, and richer topic/section metadata.
4. A trash view + bulk actions (multi-archive/delete/reindex).
5. Activate the AI placeholders (summaries/chat/flashcards) using the metadata accessor.
6. Content-hash duplicate detection (not just filename) and cross-workspace dedup of identical files.
```
