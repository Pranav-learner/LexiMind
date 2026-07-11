# Phase 3 — Module 6: Smart Notes Engine

> Status: ✅ Complete. Backend (10 files) + frontend (12 files) + 4 test suites (41 new tests, all
> passing; 251 total tests green with no regressions across Phase 1/2 and Modules 1–5).

---

## 1. Module Overview

**Why Smart Notes matter.** LexiMind already turns documents into answers (Chat) and grounded
recaps (Summaries). But those artifacts are *ephemeral consumption* — you read them and move on.
A knowledge platform needs *durable production*: a place where AI output becomes the user's own,
editable, organized, long-lived knowledge. That is what the Smart Notes Engine adds. Notes are the
first **first-class, user-owned knowledge asset** in LexiMind.

**Summaries vs Notes.**

| | Summary (Module 5) | Note (Module 6) |
|---|---|---|
| Ownership | AI owns it | **User owns it** |
| Mutability | Read-only (regenerate replaces) | **Fully editable** (rich Markdown) |
| Lifespan | Transient recap | **Persistent knowledge base entry** |
| Structure | Fixed sections | Sections *seed* an editable body |
| Organization | List + type filter | **Tags, pin, favorite, archive, search, outline** |
| Provenance | Citations per section | Citations survive editing (keyed to the note) |
| Creation | From documents | From documents, **summaries, chat, PDF selection, or blank** |

**Knowledge-management philosophy.** A note should feel like a lightweight Notion/Obsidian page
that happens to be *grounded* — every AI-generated claim carries a click-through citation into the
source PDF, and editing never severs that provenance. The user can start from AI structure and
refine, or start blank and pull evidence in. Over time a workspace accumulates a personal,
searchable, cited knowledge base.

---

## 2. Previous Architecture (how generated knowledge was handled before)

Before Module 6, every piece of AI-generated knowledge was **terminal output**:

- **Chat answers** lived only inside a conversation transcript. You could copy the text, but there
  was no way to keep, edit, retitle, tag, or organize an answer as a standalone artifact.
- **Summaries** were regenerate-only: the sections were owned by the generator. Editing a summary
  meant exporting Markdown and leaving LexiMind.
- **PDF selections** offered "Note" and "Create Note" actions in the viewer, but they were stubs
  (`live: false`, "coming soon") — the workspace even reserved a `note_count` counter and a Notes
  sidebar tab in anticipation.

**Limitations:** no persistence of edits, no organization primitives (tags/pin/search), no editor,
no way to combine AI structure with human authorship, and citation provenance was locked inside the
producing module. Knowledge could be *generated* but never *cultivated*.

---

## 3. New Architecture

```
                          ┌─────────────────────────────────────────────┐
   Documents ── Retrieval ── Context Engineering ── LLM  (Phases 1 & 2)  │
                          └───────────────┬─────────────────────────────┘
                                          │ grounded sections + citations
                                          ▼
   ┌──────────────────────────────  Notes Domain  ──────────────────────────────┐
   │  Blank ─┐                                                                   │
   │  Doc ───┤                                                                   │
   │  Summary┤─► NoteService.create* ─► Note (+ Sections + Citations + Tags)     │
   │  Chat ──┤        (one model, every path)          │                        │
   │  PDF sel┘                                          ▼                        │
   │                                          Rich Markdown Editor (autosave)    │
   │                                                    │                        │
   │                                                    ▼                        │
   │                                     Persistent, editable Knowledge Base     │
   └────────────────────────────────────────────────────────────────────────────┘
```

Key property: **the AI path reuses the production Retrieval + Context Engineering pipelines
verbatim** (via `PipelineNotesEngine`), exactly as Summaries and Chat do. No second RAG stack
exists. Once generated, a note leaves the AI path and becomes an ordinary editable document; its
citations persist as independent rows so editing the body never orphans them.

---

## 4. Database Design

Five new tables (SQLite today; additive `create_all`, no migration — consistent with the rest of
the young schema). Defined in `backend/app/notes/models.py`.

### `notes`
The knowledge asset. Notable columns:
- `id, workspace_id, owner_id` — ownership + isolation (every query is scoped to both).
- `document_id, document_ids (JSON), scope, conversation_id, folder_id, parent_note_id` —
  provenance and back-links. `scope`/`document_ids` drive AI generation; `folder_id`/`parent_note_id`
  are present-but-unused hooks for **folders** and **version history**.
- `source` (blank|document|summary|chat|selection), `note_type` (quick|study|detailed|chapterwise|
  concept|revision), `created_by` (user|ai).
- `title, description, content (Markdown, canonical editable body), editor_format`.
- `status, progress, stage, error` — async generation lifecycle (manual notes are born `ready`).
- `is_pinned, is_favorite, is_archived` — organization flags (each indexed for dashboard rails).
- `word_count, reading_time, section_count, citation_count` — recomputed on every content write.
- `model_name, prompt_version, token_usage, generation_ms` — AI telemetry.
- **`version`** — increments on every persisted content change → optimistic-concurrency for autosave
  and a future snapshot key for history.
- `deleted_at` (soft delete), `last_opened_at`, `created_at`, `updated_at`.

### `note_sections`
The AI's original structure (heading + order + content + citation_count). Seeds `content`; the live
outline the UI renders is *derived from `content` headings* so it stays correct after edits.

### `note_citations`
Grounded provenance: `note_id` (**primary link** — survives edits), optional `note_section_id`,
`document_id` (vector id), `chunk_id`, `page_number`, `workspace_id`, `citation_text`, `confidence`.
Keying to the note (not a text offset) is the design that lets free-form editing never destroy a
citation.

### `tags` + `note_tags`
Workspace-scoped labels (`name`, `color`, denormalized `note_count`) with a unique
`(workspace_id, owner_id, name)` constraint, and a `note_tags` join table (composite PK).

### Relationships & indexes
- `notes`: `ix_notes_owner_ws`, `ix_notes_ws_updated`, `ix_notes_ws_pinned` + single-column indexes
  on `document_id`, `is_pinned/favorite/archived`, `status`.
- `note_sections`: `ix_note_sections_note_order`. `note_citations`: indexed by `note_id`,
  `note_section_id`, `workspace_id`. `note_tags`: `ix_note_tags_tag`.

### Scalability
Denormalized counters (`Workspace.note_count`, `Tag.note_count`, per-note `word/section/citation`)
keep the dashboard O(1) per row — no COUNT(*) fan-out. Content search is a `LIKE` over
title+content today; the schema is ready for a semantic notes index (embeddings) without shape
changes.

---

## 5. Backend Architecture

Layered identically to every other domain (`backend/app/notes/`):

- **`models.py`** — the 5 ORM tables above.
- **`schemas.py`** — Pydantic DTOs (`NoteCreate`, `NoteGenerate`, `NoteMetaUpdate`,
  `NoteContentUpdate`, `AssistRequest/Response`, `Tag*`, `NoteOut`/`NoteDetail`) + list enums.
- **`validation.py`** — pure: title/type/scope/tag/color validation, `word_count`,
  `reading_minutes`, and `outline_from_markdown` (fenced-code-aware heading extraction).
- **`errors.py`** — transport-agnostic errors carrying `status_code`, incl. `NoteConflict` (409
  optimistic-concurrency) and `DuplicateTagName`.
- **`repository.py`** — the ONLY SQL. Owner+workspace scoped, soft-delete aware, batched
  section/citation/tag reads (no N+1), tag association wiring + counter maintenance.
- **`engine.py`** — `PipelineNotesEngine`: the ONLY bridge to the AI pipeline. Plans sections per
  template, runs retrieval→context→LLM per section, and serves synchronous AI-assist. Heavy imports
  are lazy so `app.notes.*` imports with no faiss/torch.
- **`service.py`** — all business logic: every creation path, `generate_now` (the generation
  pipeline the runner drives), autosave with conflict detection + metrics, metadata commands, tag
  lifecycle, conversions, duplicate/delete, and workspace-counter upkeep.
- **`runner.py`** — `NoteRunner` (ThreadPool prod, own DB session) + `InlineRunner` (synchronous,
  tests) + `DeferredRunner` (no-op). Same `submit(note_id)` contract as Summaries.
- **`api.py`** — two thin routers (`/notes`, `/tags`). Business logic never lives here; handlers
  translate domain errors → HTTP.

### Generation pipeline (`NoteService.generate_now`)
Mirrors Summaries: reload by trusted id → `clear_sections` → `processing` → consume engine events
(`plan`/`section`/`final`), persisting each section + its citations, tracking progress, honoring
cancellation between sections → assemble sections into the editable `content` → recompute metrics →
`completed`. On exception: `failed` with the error text, partial sections retained.

### Autosave & validation
`save_content` enforces `validate_content` (500 KB cap), checks `base_version` against the row
(stale → `NoteConflict`/409), **skips the write entirely if nothing changed** (no version bump, no
row churn), recomputes `word_count`/`reading_time`, and bumps `version`.

### Error handling
Every service method raises typed domain errors; `api._handle` maps them to `HTTPException` with the
carried `status_code`. Workspace verification (`_verify_workspace`) 404s foreign/absent workspaces
before any note work.

---

## 6. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/notes.ts`** — full client (CRUD, generate, conversions, autosave, assist, tags, export,
  `pollNoteStatus`). Same shape as `api/summaries.ts`.
- **`pages/NotesDashboard.tsx`** — the knowledge base: toolbar (search/type/pinned/archived/sort) +
  tag rail + paginated `NoteCard` grid + `NewNoteModal`. Debounced search, AbortController-guarded
  fetches, and a "make notes from this" hand-off (document/summary/chat) via router state.
- **`pages/NoteEditorPage.tsx`** — the editor experience: a 3-column workbench
  (**outline + tags** rail · **Markdown editor** · **AI-assist + citations** rail), robust autosave,
  live generation progress, reading/editing modes, export/delete, conflict recovery.
- **`components/notes/`** — `MarkdownEditor` (the editor engine), `NoteCard`, `NotesToolbar`,
  `NewNoteModal`, `constants.ts` (type/status metadata, assist catalog, tag colors, relative time).

### State management & routing
No global store (consistent with the app): each page owns its query/editor state with
`useState`/`useRef`, effects guarded by `AbortController`. Routes added to `App.tsx` under the
existing workspace nesting: `/workspace/:workspaceId/notes` and `/notes/:noteId`. The editor holds
`content`/`title` locally and the last server-acked `version` in a ref (the autosave base).

### Citation panel
Reuses the chat/summary `chat-citation` card markup. Click → `getDocumentByVector` (Module 3) →
navigate to the PDF viewer with `state:{citation:{page,text}}`, which highlights the evidence.

---

## 7. AI Integration

Note generation reuses the production stack with **no duplicate AI pipeline**:

```
PipelineNotesEngine.generate(note, db):
  plan  = template → [(heading, query)]        # study/quick/concept/revision fixed; detailed/
                                               # chapterwise derive from the doc's real headings
  for heading, query in plan:
     result = pipeline.run(query, embed_fn=generate_embedding, filters=build_filter({workspace, doc, exclude_hidden}))
     ctx    = context_builder.build(query, result.chunks, query_keywords=result.analysis.keywords)
     content = complete(build_notes_prompt(note_type, heading, ctx.context))   # STRUCTURED prompt
     cits    = structured_citations(ctx.evidence)                              # preserved provenance
     yield section(heading, content, cits)
```

This threads through **Query Analysis → Hybrid Retrieval → RRF → Reranker → Duplicate Detection →
Evidence Ranking → Compression → Context Assembly** (Phases 1–2) exactly as Summaries/Chat do.
`build_notes_prompt` (in `services/answer_service.py`) forces *structured* output (headings,
bullets, key concepts, examples) rather than prose paragraphs.

**Citation preservation:** `structured_citations(ctx.evidence)` returns the vector `document_id`,
`chunk_id`, `page_number`, `text`, and `confidence` — persisted as `NoteCitation` rows keyed to the
note. Editing the Markdown body never touches them.

**AI-assisted editing** (`PipelineNotesEngine.assist`) reuses the same pipeline for the *grounded*
operations (Expand, Add examples — it retrieves workspace evidence for the selection) and
`complete()` directly for the rest (Rewrite, Simplify, Grammar, Summarize, Quiz, Flashcards).

---

## 8. Rich Editor Design

**Choice: a Markdown-based rich editor** (`components/notes/MarkdownEditor.tsx`) — a formatting
toolbar driving a `<textarea>` source pane with a live `react-markdown`/GFM/`rehype-highlight`
preview (edit · split · preview modes).

**Why not TipTap/ProseMirror/Slate?**
1. **Zero new dependencies** — `react-markdown` + `remark-gfm` + `rehype-highlight` are already in
   the bundle (used by Chat/Summaries). No install step, no supply-chain/offline risk, build stays
   green.
2. **Citations can't be orphaned** — editing plain Markdown can't corrupt citation rows (they're
   keyed to the note, not text offsets). A WYSIWYG doc model would need custom marks to keep them.
3. **Native import/export** — the stored form *is* the export form; `⬇ Export` is a passthrough.
4. **Maturity** — the GitHub/Reddit/StackOverflow authoring model; proven for long-form.
5. **Pluggable** — the editor exposes an imperative handle (`getSelection` / `replaceSelection` /
   `insert` / `focus`); a ProseMirror engine can replace the internals later behind the same
   contract without touching the page.

**Supported formatting:** headings (H1–H3), bold/italic/strikethrough/inline-code, bullet/numbered/
**checklist** lists, quotes, **code blocks**, **tables**, links, dividers — plus `Ctrl/⌘+B/I`
shortcuts and Tab-to-indent. Images & math render through Markdown/GFM (future first-class UI).

**Autosave strategy:** debounced 1s after any edit; `Ctrl/⌘+S` forces an immediate flush; a
"Saving… / ✓ Saved / Unsaved… / ⚠ Save failed" indicator reflects state. Optimistic concurrency via
`base_version`: a stale save 409s and the UI shows a non-destructive "reload latest" banner (never
clobbers a newer edit). Unchanged content is a no-op server-side.

**Performance:** the preview is only mounted in split/preview modes; the source pane is a native
textarea (no virtual DOM per keystroke beyond React's controlled value); metrics/outline are
recomputed with `useMemo`.

---

## 9. API Documentation

All routes are authenticated and workspace-scoped. Base: `/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success | Notable errors |
|---|---|---|---|---|
| POST | `/notes` | Create manual note (blank/selection/chat paste) — accepts `citations` | 201 `NoteDetail` | 422 validation |
| POST | `/notes/generate` | **AI generate** (async) | 202 `NoteOut` (queued) | 422 bad type/scope |
| POST | `/notes/from-summary/{summary_id}` | Convert a summary → editable note | 201 `NoteDetail` | 404 source |
| POST | `/notes/from-message/{message_id}` | Save a chat answer → note | 201 `NoteDetail` | 404 source |
| GET | `/notes` | List (search/type/source/tag/status/archived/pinned/sort/paginate) | 200 `NoteListResponse` | |
| GET | `/notes/{id}/status` | Lightweight generation poll | 200 `NoteOut` | 404 |
| GET | `/notes/{id}` | Detail (content, sections, citations, tags, derived outline) | 200 `NoteDetail` | 404 |
| PUT | `/notes/{id}/content` | **Autosave** (`content`, `base_version`, `title?`) | 200 `NoteOut` | **409 conflict** |
| POST | `/notes/{id}/assist` | AI-assisted edit on a selection | 200 `AssistResponse` | 422 bad op |
| PATCH | `/notes/{id}` | Metadata (title/description/pin/favorite/archive) | 200 `NoteOut` | 404 |
| PUT | `/notes/{id}/tags` | Replace a note's tag set | 200 `NoteOut` | 404 |
| POST | `/notes/{id}/regenerate` | Re-run AI (new version) | 200 `NoteOut` | 409 (non-AI note) |
| POST | `/notes/{id}/cancel` | Cancel generation | 200 `NoteOut` | 409 (terminal) |
| POST | `/notes/{id}/duplicate` | Copy note + sections + citations | 201 `NoteDetail` | 404 |
| GET | `/notes/{id}/export?format=md` | Download Markdown (with sources) | 200 `text/markdown` | 404 |
| DELETE | `/notes/{id}?permanent=` | Soft (default) or hard delete | 204 | 404 |
| GET/POST | `/tags`, PATCH/DELETE `/tags/{id}` | Tag CRUD | 200/201/204 | 409 duplicate |

**Example — generate:** `POST /notes/generate {"note_type":"study","scope":"document",
"document_id":"doc_..."}` → `202 {id, status:"queued", created_by:"ai", ...}`; poll
`GET /notes/{id}/status` until `completed`; then `GET /notes/{id}` for content + citations.

**Example — autosave conflict:** two tabs edit the same note; the second `PUT /content` with a stale
`base_version` returns `409 {"detail":"This note was modified elsewhere ..."}`.

---

## 10. Performance Optimizations

- **Autosave:** 1s debounce + skip-if-unchanged (no version bump / row write for no-op saves) +
  optimistic concurrency (no locking). `⌘+S` for an explicit flush.
- **List rendering:** light `NoteOut` DTO (no `content` shipped to the grid); pinned-first ordering
  in SQL; denormalized counters avoid COUNT(*).
- **No N+1:** `tags_for`, `sections`, `citations_for` are batched by id sets.
- **Editor:** preview mounted only when visible; `useMemo`'d outline/metrics; native textarea.
- **Indexing:** composite indexes for the exact dashboard access patterns (owner+ws, ws+updated,
  ws+pinned) and the tag-filter subquery.
- **Search indexing:** title+content `LIKE` today; schema/endpoint shaped so a semantic notes index
  slots in behind the same list contract (see §13).
- **Caching:** metrics (`word_count`/`reading_time`) are precomputed and stored, not derived on read.

---

## 11. Testing

**Unit tests**
- `test_notes_validation.py` (10) — titles, note types, scope inference/rules, content cap, tag
  name/color, word-count (code-fence-aware), reading time, `outline_from_markdown`, default titles.
- `test_notes_repository.py` (7) — create/get scoping, soft-delete hiding, list filters
  (search/pinned/archived/type + pinned-first ordering), section/citation round-trip, `clear_sections`
  keeps free-standing citations, tag CRUD + association counters, `tag_name_exists`.
- `test_notes_service.py` (11) — blank create + metrics, citations, autosave version bump +
  **conflict** + no-op skip, `generate_now` (sections/content/citations), regenerate guard, cancel
  guard, pin/favorite/archive, tag lifecycle + duplicate-name, duplicate copies, assist delegation.

**Integration tests** (`test_notes_api.py`, 13) — the full flow over HTTP with the inline runner +
fake engine:

```
Workspace → (Document) → Generate Notes → Retrieval → Context → LLM (faked) → Persist
          → Autosave (+conflict) → AI-assist → Tags/filter → Convert(summary,chat) → Export → Delete
```

Covers auth/scoping (401/404), blank+selection create (with citations), async generation
(queued→completed, sections+citations+**derived outline**), validation 422s, autosave + 409
conflict, assist ops + unknown-op 422, pin/archive + list filters, content search, tag CRUD +
attach + filter + usage counter, **summary→note** and **chat-message→note** conversions, duplicate/
export/delete, and document-scoped generate + regenerate + cancel-conflict.

**Results:** 41 new tests pass. Full suite: **251 passed** (only `test_reranker`/`test_eval` skipped
— they require torch/sentence-transformers, a pre-existing environment constraint unrelated to this
module). **No regressions** in Phase 1, Phase 2, or Modules 1–5. Frontend `tsc -b` + `vite build`
are green; the new lint errors count is zero in Notes files.

---

## 12. File Changes Summary

### New backend files
- `backend/app/notes/__init__.py` — package doc.
- `backend/app/notes/models.py` — Note/NoteSection/NoteCitation/Tag/NoteTag (5 tables).
- `backend/app/notes/schemas.py` — DTOs + list enums.
- `backend/app/notes/validation.py` — pure validation + text metrics + outline derivation.
- `backend/app/notes/errors.py` — domain errors incl. `NoteConflict`.
- `backend/app/notes/repository.py` — all SQL (notes/sections/citations/tags/associations).
- `backend/app/notes/service.py` — lifecycle, autosave, tags, conversions, generation pipeline.
- `backend/app/notes/engine.py` — `PipelineNotesEngine` (generation + assist; the AI bridge).
- `backend/app/notes/runner.py` — background/inline/deferred runners.
- `backend/app/notes/api.py` — `/notes` + `/tags` routers.
- `backend/tests/test_notes_{validation,repository,service,api}.py` — 41 tests.

### New frontend files
- `src/api/notes.ts`, `src/pages/NotesDashboard.tsx`, `src/pages/NoteEditorPage.tsx`,
  `src/components/notes/{MarkdownEditor,NoteCard,NotesToolbar,NewNoteModal,constants}.tsx/.ts`,
  `src/styles/notes.css`.

### Modified files (why)
- `backend/app/db/base.py` — register notes models in `init_db()` so `create_all` builds the tables.
- `backend/app/main.py` — mount `notes_router` + `notes_tag_router`.
- `backend/app/services/answer_service.py` — add `build_notes_prompt`, `NOTE_ASSIST_OPS`,
  `NOTE_ASSIST_GROUNDED`, `build_note_assist_prompt` (the notes-specific prompts; no new AI stack).
- `backend/tests/conftest.py` — import notes models, add `FakeNotesEngine`, override the notes
  runner (inline) + assist engine so the suite stays faiss/torch-free.
- `src/App.tsx` — add the two notes routes.
- `src/types.ts` — add the Notes/Tag TypeScript contracts.
- `src/main.tsx` — import `styles/notes.css`.
- `src/pages/WorkspaceDetail.tsx` — add the "📝 Notes" entry point.
- `src/pages/ChatWorkspace.tsx` + `src/components/chat/ChatMessage.tsx` — "📝 Save as note" on
  assistant answers → `noteFromMessage` → open editor.
- `src/components/summary/SummaryViewer.tsx` — "📝 To notes" → `noteFromSummary` → open editor.
- `src/pages/PdfViewer.tsx` + `src/components/viewer/actions.ts` — the "Note"/"Create Note"
  selection actions are now **live**: create a citation-anchored note from the highlighted text.

---

## 13. Future Compatibility

The schema and boundaries were chosen to make the next modules additive:

- **Flashcards** — the assist engine already emits flashcards/quiz from a selection; a `flashcards`
  table can back-reference `note_id`/`note_section_id`. `Workspace.flashcard_count` is pre-wired.
- **Knowledge Graph** — `parent_note_id` + citation `document_id`/`chunk_id` give note↔note and
  note↔document edges; a `note_links` table drops in without touching `notes`.
- **AI Tutor** — notes are grounded, structured, and queryable; a tutor can retrieve over a user's
  notes (semantic notes index) the same way retrieval works over documents today.
- **Research Reports** — multi-note synthesis reuses the exact generation pipeline; a report is a
  note whose scope is a set of notes.
- **Collaborative editing** — `owner_id`, `version` (optimistic concurrency), and the section model
  are the substrate; presence/CRDT sits on top of the existing autosave contract.
- **Agentic workflows** — every capability is a clean service method behind a typed API, so an agent
  can create/generate/edit/tag notes through the same surface a human uses.
- **Folders & version history** — `folder_id` and `parent_note_id` columns exist and are indexed;
  only UI + a `note_versions` table are needed.

---

## 14. Lessons Learned

**Architecture decisions**
- *Reuse over rebuild.* Modeling Notes on the Summaries module (engine/runner/service split, event
  protocol, inline test runner) meant the AI path was correct on day one and the test harness
  extended trivially. The single most important rule — "the engine is the only bridge to AI" — kept
  the retrieval/context pipelines singular.
- *One model, many doors.* Every creation path funnels through one `Note` + `NoteService`, so blank,
  document, summary, chat, and selection notes are the same object with different provenance. This
  avoided five half-baked note variants.
- *Citations keyed to the note, not the text.* This one decision is what makes "editing must not
  remove citations" true by construction rather than by careful diffing.

**Tradeoffs**
- *Markdown editor vs WYSIWYG.* We traded rich inline-widget editing for zero-dependency robustness,
  trivial export, and citation safety. The imperative-handle boundary keeps the upgrade path open.
- *`LIKE` search vs semantic.* Simple and index-friendly now; the contract is shaped for a semantic
  index later. Honest limitation, not a dead end.
- *Autosave debounce.* A pending edit within the last ~1s before an abrupt unmount can be lost; the
  explicit `⌘+S` and short debounce make this acceptable. A `sendBeacon`/`keepalive` flush is the
  obvious hardening.

**Known limitations**
- Note content search is lexical (no semantic recall yet).
- Folders, version history, and collaboration are schema-ready but UI-absent (by design — this
  module deliberately did not implement them).
- AI-assist is synchronous; very long selections are bounded by the LLM call latency (no streaming).

**Future improvements**
- Semantic notes index + "related notes" surfacing; streaming assist; folders/version-history UI;
  first-class image/math editing; `sendBeacon` autosave flush; per-section regeneration.
```
```

---

### Success criteria — status

✅ Codebase audited · ✅ Smart Notes domain implemented · ✅ AI-generated notes · ✅ Rich text editor ·
✅ Citation preservation · ✅ AI-assisted editing · ✅ Search & tagging · ✅ Autosave · ✅ Performance
optimized · ✅ Tests passing (41 new, 251 total) · ✅ No regressions in Phase 1/2 + Modules 1–5 ·
✅ Documentation complete (this file).
