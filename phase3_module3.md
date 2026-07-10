# LexiMind — Phase 3 · Module 3: Intelligent PDF Viewer & Citation Navigation

> **Status:** ✅ Complete · **New backend tests:** 13/13 passing (149 in the light env, incl.
> the shared Phase-1/2 + Module-1/2 suites) · **Frontend:** builds clean (`tsc -b && vite build`,
> `pdfjs-dist`) · **Builds on:** [phase1.md](./phase1.md), [phase2.md](./phase2.md),
> [phase3_module1.md](./phase3_module1.md), [phase3_module2.md](./phase3_module2.md)
>
> The canonical reference for Phase 3, Module 3. A new engineer should understand the whole PDF
> Viewer — backend viewer APIs, the citation-navigation contract, AI reuse, and the frontend
> reader — from this file alone.
>
> **One-line goal:** turn LexiMind from "chat with a PDF" into an **interactive AI document
> reader** where a user moves seamlessly between an AI answer and the exact page/passage it came
> from.

---

## Table of Contents
1. [Module Overview](#1-module-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Viewer Architecture](#4-viewer-architecture)
5. [Citation Navigation](#5-citation-navigation)
6. [AI Integration](#6-ai-integration)
7. [Frontend Architecture](#7-frontend-architecture)
8. [Backend APIs](#8-backend-apis)
9. [Performance Optimizations](#9-performance-optimizations)
10. [Testing](#10-testing)
11. [File Changes Summary](#11-file-changes-summary)
12. [Future Compatibility](#12-future-compatibility)
13. [Lessons Learned](#13-lessons-learned)

---

## 1. Module Overview

### Why an integrated PDF Viewer matters
Modules 1–2 gave LexiMind workspaces and a Document Library — you could upload, browse, and
manage PDFs, and ask questions whose answers came with citations like `[Source: OS.pdf Page
142]`. But those citations were a **dead end**: text on a screen. To verify an answer you had to
leave the app, open the PDF elsewhere, and hunt for page 142. The knowledge and its source lived
in two disconnected places.

The PDF Viewer closes that loop. It makes the source material a **first-class, in-app reading
surface** and wires the AI's citations directly to it: click a citation → the document opens →
scrolls to the page → **highlights the exact referenced passage**. It also flips the direction —
select any passage in the PDF and **ask the AI about it**, reusing the existing retrieval +
context pipeline. The viewer becomes the central interface for interacting with knowledge.

### How it improves the experience
- **Trust through verification** — every AI claim is one click from its source passage.
- **Bidirectional flow** — answer → source (citation navigation) *and* source → answer (select &
  ask).
- **A real reader** — zoom, rotate, continuous scroll, full-text search, thumbnails, outline,
  keyboard navigation, fullscreen, download.
- **Continuity** — the reader restores your last page/zoom/rotation and keeps a "recently viewed"
  history, so reading resumes where you left off.

---

## 2. Previous Architecture

Before Module 3 a "PDF" existed only as bytes on disk (`Document.storage_path`) and as chunks in
the vector index. There was **no way to see it in the app**:

```
Library card / detail drawer  →  (metadata only; no rendering)
Ask question  →  /query  →  answer + a formatted `sources` STRING  →  dead-end text
```

| Concern | Before Module 3 |
|---|---|
| Rendering | none — no PDF viewer, no way to open a file in-app |
| File access | `storage_path` in the DB; **no endpoint served the bytes** |
| Citations | `/query` returned a human-readable `sources` string only — not clickable, no machine fields |
| Source navigation | impossible — the answer and the page it cited were disconnected |
| Select → ask | impossible — no reading surface to select from |
| Reading continuity | none — no page/scroll/zoom memory, no history |

### Limitations
1. **No reader** — the app could talk *about* documents but never *show* them.
2. **Citations weren't actionable** — a string, not a link to a page + passage.
3. **No file-serving API** — even a custom viewer had nothing to fetch.
4. **One-directional AI** — you could ask the corpus, but not "explain *this* selected passage."
5. **No session continuity** — every open started from page 1.

> **The latent seam:** every chunk already carried `document_id`, `page_number`, and `section`,
> and Module 2 gave the file a `storage_path` and a `Document` row. Module 3 exposes those as
> **viewer APIs** and threads them into a renderer — again completing a seam rather than inventing
> one.

---

## 3. New Architecture

```
   Document Library (Module 2)
        │  "Open in viewer"
        ▼
   PDF Viewer  ── GET /documents/{id}/file (bytes) ─▶ PDF.js render (canvas + text layer)
    │  │  │        GET /documents/{id}/chunks       ─▶ highlight text · section outline
    │  │  └─ Reading session ── PUT/GET /reading/{id}/progress ─▶ restore page/zoom/rotation
    │  │                        GET /reading/history          ─▶ recently viewed
    │  ▼
    │  Citation Navigation
    │     AI answer citation {document_id(vector), page, text}
    │        │  same doc → jump+highlight
    │        │  other doc → GET /documents/by-vector/{id} → open that viewer → jump+highlight
    ▼
   AI Interaction (select text → Ask LexiMind)
        selection ─▶ askQuestion() ─▶ POST /query (workspace-scoped)
                     ─▶ Phase-1 retrieval → Phase-2 context → LLM
                     ─▶ answer + STRUCTURED citations ─▶ clickable chips ─▶ back into the viewer
```

### Two directions, one loop
- **Answer → Source:** `/query` now returns **structured `citations`** (vector `document_id`,
  `source`, `page_number`, `section`, `text` snippet). The viewer resolves and navigates them.
- **Source → Answer:** selecting text in the viewer feeds `askQuestion()` → the **unchanged**
  `/query` pipeline → an answer whose citations feed straight back into the viewer.

No retrieval logic is duplicated; Module 3 is a **reading + navigation layer** over the existing
pipeline plus a handful of **additive, read-mostly** backend endpoints.

---

## 4. Viewer Architecture

Rendering uses **PDF.js (`pdfjs-dist`)** — the production-standard, framework-agnostic engine —
driven directly (no heavy React wrapper) so it works cleanly with React 19 + Vite. The frontend
is deliberately **modular and decoupled** (rendering / navigation / search / selection /
highlight / citation / toolbar / sidebar are separate units):

| Concern | Unit | Responsibility |
|---|---|---|
| Document loading | `usePdfDocument` | fetch bytes (with token) → `getDocument` → `pdf`, `numPages`, `outline`, page cache |
| Rendering | `PdfPage` / `PdfCanvas` | one page = canvas + text layer at a scale+rotation; **virtualized** continuous scroll |
| Navigation | `PdfToolbar` + page container | prev/next, jump-to-page, keyboard, current-page + reading-progress tracking |
| Zoom / rotation | `PdfToolbar` | zoom in/out, **fit width / fit page / reset**, rotate left/right, fullscreen |
| Search | `PdfSearch` | full-text scan of `getTextContent()`, next/prev, **match counter**, highlight |
| Selection | `SelectionMenu` | floating actions on text selection (Ask AI / Copy / Note / Flashcard / Highlight) |
| Context menu | `ContextMenu` | right-click actions (extensible) |
| Highlight | `useCitationHighlight` | jump + smooth-scroll + mark matching text-layer spans; timeout or persist |
| Citation | `AiPanel` chips + highlight hook | render structured citations, click → navigate + highlight |
| Sidebar | `PdfSidebar` | thumbnails · outline · search results · recent pages · future notes/annotations |
| Session | `useReadingSession` | restore + debounced-save page/zoom/rotation (server + localStorage) |

### Highlight system
The text layer renders selectable, absolutely-positioned spans over each page. To highlight a
citation, the hook finds the spans whose text matches the citation's `text` snippet (from
`/query` or `/chunks`) and applies a `.pdf-highlight` class (animated). Highlights either **fade
after a configurable timeout** (default ~6s) or **persist until cleared**, and **multiple
citations** can be highlighted at once.

### Session management
`useReadingSession` restores the last page/zoom/rotation on open (from the server, with a
localStorage cache for instant paint) and **debounced-saves** on change via
`PUT /reading/{id}/progress`. `GET /reading/history` powers a "recently viewed" list.

---

## 5. Citation Navigation

This is the module's core feature and the reason the backend changed.

### The flow
```
AI answer contains a citation  {chunk_id, document_id(vector), source, page_number, section, text}
        │
        ├─ citation's document == the open document?
        │      YES → navigate to page_number → smooth-scroll → highlight `text` in the text layer
        │      NO  → GET /workspaces/{ws}/documents/by-vector/{document_id}  (resolve → real doc id)
        │            → route to /workspace/{ws}/document/{realId} → then jump + highlight
        ▼
   focus the reader on the exact passage; highlight times out or persists per setting
```

### Page lookup & metadata mapping
Every citation maps cleanly through the existing metadata:
```
Workspace (workspace_id)
   └── Document (Document row; resolved from the citation's vector document_id)
         └── Page (page_number — already on every chunk)
               └── Chunk (chunk_id; text via /chunks or the citation snippet)
                     └── Text (highlighted in the text layer)
```
- **Vector id → Document row:** `GET /documents/by-vector/{vector_document_id}` uses
  `DocumentRepository.get_by_vector_id` (added in Module 2) — the citation's `document_id` is the
  vector id, so this is the bridge to the real `Document.id` and its viewer route.
- **Chunk → highlight text:** the structured citation carries a `text` snippet; for richer
  per-page highlighting the viewer can also call `GET /documents/{id}/chunks?page=N`, which returns
  every chunk on that page (text + section) sorted by position.

### No information loss
Structured citations are built from `ContextResult.evidence` — the same objects Phase 2 produced
after dedup → evidence-ranking → compression → assembly. Because Phase 2 already guarantees
**citation preservation** (every `Evidence` owns a non-empty `citations` list; merges union them),
the viewer sees exactly the provenance the context engine kept — nothing is dropped between the
LLM answer and the highlighted passage.

---

## 6. AI Integration

Selecting text and asking about it reuses the **entire existing pipeline** — no retrieval or
context logic is re-implemented:

```
Select text in the viewer
   ↓  (SelectionMenu / ContextMenu → "Ask AI")
AiPanel.askQuestion(selectedText, workspaceId)
   ↓
POST /query { question, workspace_id }        ← unchanged endpoint
   ↓
Phase-1 retrieval  (dense + BM25 → RRF → rerank, workspace-scoped, archived excluded)
   ↓
Phase-2 context    (dedup → rank → budget → compress → assemble, citations preserved)
   ↓
LLM (Ollama)
   ↓
answer + STRUCTURED citations  → clickable chips in the AI panel → back into the viewer
```

The only backend change on the AI path is **additive**: `/query` now returns a machine-readable
`citations` array alongside the existing `answer` and `sources` string, via a new pure helper
`answer_service.structured_citations(evidence)`. Existing `/query` consumers are unaffected.

---

## 7. Frontend Architecture

**Stack additions:** `pdfjs-dist` (PDF rendering + text extraction). Everything else unchanged
(React 19 + Vite + react-router v7 + auth Context + `fetch`). The PDF worker is bundled via a
Vite `?url` import and set on `pdfjsLib.GlobalWorkerOptions.workerSrc`.

### Pages & routing
| Route | Page | Purpose |
|---|---|---|
| `/workspace/:workspaceId/library` | `DocumentsLibrary` | now opens documents in the viewer |
| `/workspace/:workspaceId/document/:documentId` | `PdfViewer` | the reader (Toolbar / Sidebar · Viewer · AI Panel) |

### Component hierarchy
```
PdfViewer (page — owns viewer state)
├── PdfToolbar        search · zoom · fit · rotate · page nav · fullscreen · download
├── PdfSidebar        Thumbnails | Outline | Search results | Recent | (future) Notes/Annotations
├── PdfCanvas         continuous-scroll container (virtualized)
│    └── PdfPage[]    canvas + text layer per visible page (memoized, IntersectionObserver)
│         ├── SelectionMenu   Ask AI · Copy · Note · Flashcard · Highlight
│         └── ContextMenu     Copy · Highlight · Note · Summary · Flashcard · Ask AI
└── AiPanel           question box (reuses askQuestion) + clickable citation chips
hooks: usePdfDocument · useCitationHighlight · useReadingSession
api:   src/api/viewer.ts (file/chunks/resolve/reading) + reuse api/backend.askQuestion
styles: src/styles/viewer.css (theme-aware; toolbar, 3-column layout, highlight, menus, chips)
```

### State management
- Viewer state (page, scale, rotation, search state, selection, active citations, sidebar/AI-panel
  open) is **page-local** in `PdfViewer` — consistent with the project's Context-only,
  no-Redux/Zustand convention. Cross-cutting logic is factored into hooks
  (`usePdfDocument`, `useCitationHighlight`, `useReadingSession`).
- Keyboard shortcuts: ←/→ (or PageUp/Down) page nav, +/- zoom, Esc closes menus/search/fullscreen.

---

## 8. Backend APIs

All new routes require `Authorization: Bearer <token>` and verify workspace (and, where relevant,
document) ownership. They are **additive** — no existing endpoint changed shape (except `/query`
gained one new field).

### `GET /workspaces/{ws}/documents/{id}/file` → 200 (binary)
Streams the stored file (`FileResponse`, `media_type = mime_type`, `Content-Disposition: inline`)
for PDF.js. Errors: 401 · 404 (not owned / soft-deleted / file missing on disk).

### `GET /workspaces/{ws}/documents/{id}/chunks?page=` → 200
Query: optional `page` (1-based). Response: `{ document_id, vector_document_id, total,
items: [{ chunk_id, document_id, page_number, section, chunk_index, text }] }`, sorted by
`(page_number, chunk_index)`. Powers citation highlighting, the section outline, and per-page text.
Errors: 401 · 404.

### `GET /workspaces/{ws}/documents/by-vector/{vector_document_id}` → 200
Resolves an AI citation's vector `document_id` to its `DocumentOut`. Errors: 401 · 404 (no live
document matches).

### `PUT /workspaces/{ws}/reading/{id}/progress` → 200
Body: `{ page (≥1), scroll_top (≥0), zoom (10–1000, percent), rotation }`. Upserts the single
reading session for `(owner, document)`; clamps values. Response: `ReadingSessionOut`.
Errors: 401 · 404 (workspace/document not owned).

### `GET /workspaces/{ws}/reading/{id}/progress` → 200
Response: `ReadingSessionOut | null` (null when nothing saved yet). Errors: 401 · 404.

### `GET /workspaces/{ws}/reading/history?limit=` → 200
Response: `{ items: [{ document_id, display_name, filename, file_type, page, page_count,
updated_at }] }`, newest first, live documents only. Errors: 401 · 404.

### `POST /query` → 200 (enhanced, backward compatible)
Unchanged request. Response now includes **`citations`**:
`[{ chunk_id, document_id, source, page_number, section, text }]` alongside the existing
`answer`, `sources` (string), `analysis`, `retrieval`, `context`.

### Validation & errors
Reuses the Module-2 domain-error → HTTP mapping (`DocumentError`: 404/409/413/415/422) and the
auth 401 guard. Reading-progress values are clamped in the service; unknown documents/workspaces
return 404.

---

## 9. Performance Optimizations

Built to stay smooth on **1000+ page** PDFs:

- **Virtualized rendering** — continuous scroll renders only pages near the viewport (via
  IntersectionObserver); off-screen pages are sized placeholders, so memory and paint stay bounded
  regardless of document length.
- **Lazy page + thumbnail loading** — page canvases and low-scale sidebar thumbnails render on
  demand as they scroll into view.
- **Memory cleanup** — page canvases are released on unmount; the PDF.js page cache is bounded.
- **Incremental search** — full-text search scans `getTextContent()` lazily/per-page and caches
  results, so it never blocks the UI on a huge document.
- **Debounced session saves** — reading-progress `PUT`s are debounced (~800ms) and mirrored to
  localStorage, avoiding a request per scroll tick.
- **Memoized pages + hook-isolated logic** — `PdfPage` is memoized and heavy logic lives in hooks,
  minimizing re-renders when unrelated viewer state changes.
- **Backend**: file serving is a zero-copy `FileResponse`; `/chunks` is a single read-only pass
  over the in-memory metadata; reading history is one indexed, `LIMIT`-bounded join.

---

## 10. Testing

**13 new backend tests**, all passing, on the same light harness (in-memory SQLite + minimal
FastAPI app with in-memory index/ingestion fakes; the reading router is now mounted too).

| File | Type | Covers |
|---|---|---|
| `test_citations.py` | unit | `structured_citations` shape/fields, **dedup by chunk_id preserving order**, text truncation (3) |
| `test_document_viewer.py` | **integration** | file streaming (bytes + content-type), **auth + cross-user 404**, chunks + page filter, **by-vector citation resolve** (+404), reading-progress **upsert & restore**, reading-history **recency + join fields**, foreign-document 404 (10) |

- The file endpoint is genuinely exercised: the upload writes real bytes to a temp dir, and the
  test asserts the streamed content matches.
- **No Phase-1/2/Module-1/2 regression.** The only shared files touched are additive
  (`answer_service.py` gained a pure helper; `query.py` added one response field; `main.py`/
  `conftest.py` mounted a router; `documents/models.py` added a **new table**). The full light
  suite is **149 passed**; the only non-runs are the same 4 faiss/`rank_bm25` suites that are
  environmental (not touched here).

```bash
# new + shared light suite
cd backend && python -m pytest tests/test_citations.py tests/test_document_viewer.py \
    tests/test_document_*.py tests/test_workspace_*.py tests/test_auth.py \
    tests/test_filters.py tests/test_fusion.py -q          # all green
# full suite (real venv with faiss/torch)
cd backend && ./venv/bin/python -m pytest tests/ -q
```

Frontend: `cd frontend/leximind-frontend && npm run build` (`tsc -b && vite build`) compiles clean
with `pdfjs-dist`; the viewer ships as its own lazy chunk and the PDF worker is bundled. Viewer
component/hook behavior (navigation, search, citation-highlight matching, session restore) is
structured into small, individually testable units.

---

## 11. File Changes Summary

### New files — Backend
| File | Purpose |
|---|---|
| `app/documents/reading.py` | `ReadingSessionRepository` + `ReadingService` (upsert progress, history) |
| `app/documents/reading_api.py` | `/workspaces/{id}/reading/*` routes (progress GET/PUT, history) |
| `tests/test_citations.py` | unit tests for `structured_citations` |
| `tests/test_document_viewer.py` | integration tests for file/chunks/resolve/reading |

### Modified files — Backend
| File | Reason |
|---|---|
| `app/documents/models.py` | add `ReadingSession` table (per-user page/scroll/zoom/rotation) |
| `app/documents/schemas.py` | add `ChunkOut`/`DocumentChunksResponse`, reading DTOs |
| `app/documents/indexing.py` | add `list_document_chunks` (per-page, sorted chunk read) |
| `app/documents/api.py` | add `/{id}/file`, `/{id}/chunks`, `/by-vector/{vid}` routes |
| `app/services/answer_service.py` | add `structured_citations(evidence)` helper |
| `app/api/query.py` | include structured `citations` in the response |
| `app/main.py` | mount the reading router |
| `tests/conftest.py` | mount the reading router in the test app |

### New files — Frontend
| File | Purpose |
|---|---|
| `src/api/viewer.ts` | viewer API client (token-auth file bytes + download, chunks, by-vector resolve, reading progress/history) |
| `src/pages/PdfViewer.tsx` | the reader page (Toolbar / Sidebar · Viewer · AI Panel); owns state, keyboard shortcuts, cross-doc citation resolution |
| `src/components/viewer/pdfjs.ts` | central PDF.js import + `?url` worker wiring + shared type aliases |
| `src/components/viewer/usePdfDocument.ts` | load PDF (token-auth bytes) + outline + cached `getPage`; destroys loading task on unmount |
| `src/components/viewer/PdfToolbar.tsx` | search/zoom/fit/reset/rotate/nav/fullscreen/download/print + panel toggles |
| `src/components/viewer/PdfPage.tsx` | one virtualized page (canvas + text layer), IntersectionObserver render/teardown, memoized |
| `src/components/viewer/PdfCanvas.tsx` | continuous-scroll container; current-page tracking + progress; imperative `scrollToPage` handle |
| `src/components/viewer/PdfSearch.tsx` | incremental full-text search, per-page cache, n-of-m counter, next/prev |
| `src/components/viewer/PdfSidebar.tsx` | tabs: thumbnails (lazy) · outline (+`/chunks` section fallback) · search · recent · future stubs |
| `src/components/viewer/highlight.ts` | text-span highlight/matching helpers (search hits + citation-snippet containment) |
| `src/components/viewer/SelectionMenu.tsx` | text-selection actions (Ask AI/Copy/Note/Flashcard/Highlight) |
| `src/components/viewer/ContextMenu.tsx` | right-click actions |
| `src/components/viewer/actions.ts` | shared `onAction(type,text)` action config for both menus (extensible) |
| `src/components/viewer/AiPanel.tsx` | question box (reuses `askQuestion`) + "ask about selection" + clickable citation chips |
| `src/components/viewer/useCitationHighlight.ts` | navigate + scroll + highlight; multi-citation; auto-clear (~6s) or persist |
| `src/components/viewer/useReadingSession.ts` | localStorage instant restore + server reconcile + debounced (800ms) save |
| `src/styles/viewer.css` | viewer layout, PDF.js text-layer rules, highlight, menus, chips, thumbnails (theme-aware) |

### Modified files — Frontend
| File | Reason |
|---|---|
| `src/types.ts` | add viewer types (`PdfChunk`, `DocumentChunksResponse`, `ReadingSession`, `ReadingHistoryItem`, `QueryCitation`, `QueryResponse`) |
| `src/App.tsx` | add lazy `/workspace/:workspaceId/document/:documentId` route |
| `src/main.tsx` | import `styles/viewer.css` |
| `src/pages/DocumentsLibrary.tsx` | `onView` navigates a document to the viewer |
| `src/components/document/DocumentCard.tsx` | 📖 View action + primary click opens the viewer; 👁️ keeps the detail drawer |
| `src/components/document/DocumentDetailDrawer.tsx` | "📖 Open in viewer" button |
| `package.json` | add `pdfjs-dist` (6.1.200) |

> The AI panel reuses `askQuestion` from `src/api/backend.ts` **unchanged** — it simply reads the
> new `citations` field the backend now returns, so no existing API client needed modifying.

---

## 12. Future Compatibility

The viewer is the surface the remaining knowledge features attach to:

| Future capability | What Module 3 already provides |
|---|---|
| **Smart Notes** | text selection + `SelectionMenu`/`ContextMenu` "Create Note" hook; page + chunk coordinates to anchor a note; a sidebar "Notes" tab placeholder |
| **Flashcards** | the same selection actions ("Create Flashcard"); citation/page provenance to generate a card front/back from a passage |
| **AI Summaries** | context-menu "Generate Summary"; `Document.summary_status` (Module 2) + the AI panel to render results |
| **Annotation System** | text-layer span coordinates + the `/chunks` positions give the anchor model; a "Highlight" action + sidebar "Annotations" tab are already stubbed; a future `annotations` table joins like `reading_sessions` did (new table, no migration) |
| **Multimodal support** | `media_type` (Module 2) + a per-type renderer swap — the toolbar/sidebar/AI-panel shell is media-agnostic |
| **Knowledge Graph** | citations already map Workspace → Document → Page → Chunk → Text; those edges are the graph's raw material, and `by-vector` resolution is the lookup primitive |

Every future action plugs into the extensible `onAction(type, text, {page, chunk})` seam on the
selection/context menus rather than modifying the viewer core.

---

## 13. Lessons Learned

### Architecture decisions
- **Drive PDF.js directly, don't wrap it.** A thin set of hooks/components over `pdfjs-dist`
  avoids React-19 peer-dependency friction from higher-level wrappers and keeps rendering,
  virtualization, and the text layer under our control (essential for citation highlighting).
- **Make citations structured at the source.** Rather than parse the human `sources` string on the
  client, `/query` now emits machine-readable `citations` from `ContextResult.evidence`. The
  viewer gets exact fields (vector id, page, snippet) and the display string stays for backward
  compatibility.
- **A new table, not new columns.** Reading state lives in a new `reading_sessions` table, which
  `create_all` provisions cleanly even on an existing SQLite file — sidestepping the no-Alembic
  migration gap for altered columns.
- **Reuse the pipeline, add only a reading layer.** Select-and-ask routes through the untouched
  `/query`; the backend work was a handful of additive, read-mostly endpoints. The AI stays a
  single source of truth.
- **Resolve across documents via the Module-2 seam.** `get_by_vector_id` (built for the Context
  Engine) doubles as the citation→document resolver, so cross-document citation jumps needed no new
  data model.

### Tradeoffs
- **Client-side full-text search** (scanning `getTextContent()`) rather than a server search index
  — zero new infra and works offline; a backend search endpoint can back it later for huge corpora.
- **Snippet-match highlighting** against text-layer spans is robust and simple but approximate for
  heavily reflowed text; exact glyph-range highlighting is a future refinement using the `/chunks`
  paragraph offsets.
- **Reading state is per-user, single-row-per-document** (last position wins) — not a full history
  timeline; sufficient for "resume where you left off" and "recently viewed".
- **Serving files from local disk** via `FileResponse` — fine offline-first; a future object-store
  driver swaps in behind the same endpoint.

### Known limitations
- Very large PDFs still pay PDF.js's parse cost on first open (mitigated by virtualized rendering
  after load).
- Highlight matching depends on the citation snippet appearing in the page text; scanned/OCR-only
  pages without a text layer won't highlight (they will still navigate) — `ocr_status` (Module 2)
  is the hook for a future OCR text layer.
- Print is optional/best-effort via the browser; no server-side rendering.

### Future improvements
1. Persisted annotations/highlights (new `annotations` table) surfaced in the sidebar.
2. Exact glyph-range highlighting using stored paragraph offsets from ingestion.
3. A backend search endpoint for very large documents + cross-document search.
4. Activate Notes/Flashcards/Summaries from the already-stubbed selection/context actions.
5. Thumbnail/pre-render caching and a worker pool for faster large-document navigation.
```
