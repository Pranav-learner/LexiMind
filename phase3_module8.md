# Phase 3 — Module 8: Citation Intelligence & Knowledge Explorer

> Status: ✅ Complete. Backend (10 files, a derived-index design) + frontend (6 files) + 2 test
> suites (18 new tests, all passing; **311 total tests green** with no regressions across Phase 1/2
> and Modules 1–7).

---

## 1. Module Overview

**Why citation intelligence matters.** LexiMind already grounds every AI output in citations — but
until now a citation was a dead-end label: `[1] OS.pdf Page 142`. You could click it to jump to the
PDF, and that was all. Trust in an AI system comes from *traceability* and *explainability*: a user
needs to see not just *that* an answer is sourced, but *why that evidence*, *how confident* the
system was, *where else* that evidence is used, and *what related knowledge* surrounds it. This
module turns every citation into an interactive, explainable, navigable **knowledge node**.

**Basic vs explainable citations.**

| | Basic citation (before) | Explainable citation (now) |
|---|---|---|
| What it is | A reference label | A first-class knowledge node |
| Interaction | Click → open PDF | Click → PDF **+** an intelligence panel |
| Metadata | Page number | Confidence, evidence score, retrieval path, reference count |
| Reach | One answer | Every place the evidence is reused (chat/summary/note/flashcard) |
| Discovery | None | Backlinks + related chunks (Obsidian-style) |
| Explanation | None | "Why the AI cited this" — deterministic, instant |

**How it improves trust & transparency.** Every AI answer becomes *auditable*: from answer → citation
→ evidence chunk → page → document → workspace, with the exact retrieval reasoning surfaced. Users
can verify the source, understand the selection, and explore the surrounding knowledge — the
foundation for the future Knowledge Graph and Agentic phases.

---

## 2. Previous Architecture (how citations worked before)

Citations were **per-module and write-only**. Each of Modules 4–7 persisted its own citation table:
`message_citations`, `summary_citations`, `note_citations`, `flashcard_citations` — all
structurally identical (`document_id, chunk_id, page_number, workspace_id, citation_text,
confidence`) plus one parent link. The frontend rendered them as cards and, on click, resolved the
vector `document_id` (Module 3) and jumped to the PDF page.

**Limitations:**
- **Siloed** — the same evidence chunk cited by a summary *and* a note *and* a flashcard existed as
  four unrelated rows; nothing connected them.
- **Opaque** — only `confidence` (the Phase-2 evidence score) was surfaced; the retrieval reasoning
  was discarded after generation.
- **No discovery** — no way to ask "where else is this concept cited?" or "what's related?".
- **No aggregation** — no workspace-level citation statistics or search.

Citations went *in* but were never turned into *intelligence*.

---

## 3. New Architecture

```
   LLM Response (chat / summary / note / flashcard)
        │  (Modules 4–7 already persist per-module citations)
        ▼
   message_citations · summary_citations · note_citations · flashcard_citations   ← source of truth
        │
        ▼   CitationIndexer (aggregate + dedup + co-occurrence)   ← the ONLY reader of the 4 tables
   ┌───────────────  Derived Citation Index  ───────────────┐
   │  Citation (deduped by chunk) ── CitationReference       │
   │        └── KnowledgeReference (chunk↔chunk backlinks)   │
   └───────────────────────┬─────────────────────────────────┘
                           ▼
     Evidence · References · Related Knowledge · Explain · Stats · Search
                           │
                           ▼
   Citation Panel  ──►  PDF Viewer (Module 3: navigate + highlight)
   Knowledge Explorer  ──►  Chat / Summary / Note / Flashcard (navigate to the artifact)
```

The index is a **derived, rebuildable cache** — Modules 4–7 remain the source of truth, so the
intelligence is always consistent with the data that owns it. Nothing changes retrieval behaviour;
the module only *exposes* metadata Phases 1–2 already produced.

---

## 4. Database Design

Three new tables (SQLite; additive `create_all`). Defined in `backend/app/citations/models.py`.

### `citations`
One deduped citation per distinct evidence chunk in a workspace. Key columns: `id, workspace_id,
owner_id, document_id (vector id), chunk_id, group_key (natural dedup key = chunk_id or synthetic),
page_number, paragraph_number (future), citation_text`; scores `confidence, retrieval_score
(nullable), reranker_score (nullable), evidence_score`; `reference_count (denormalized), created_at`.
**Unique** `(workspace_id, group_key)`.

### `citation_references`
A polymorphic link recording every place a citation is used: `id, citation_id, workspace_id,
reference_type (message|summary|note|flashcard)`, typed FKs `message_id/summary_id/note_id/
flashcard_id`, denormalized navigation/display `ref_parent_id` (conversation/summary/note/deck),
`ref_child_id` (message/section/card), `ref_title`, and `source_row_id` (the original row, for
idempotency). **Unique** `(citation_id, reference_type, source_row_id)`.

### `knowledge_references`
A chunk↔chunk relationship (the Knowledge-Graph seed): `id, citation_id, workspace_id,
related_chunk_id, related_document_id, related_citation_id, relationship (co_reference|
same_document), strength, created_at`. **Unique** `(citation_id, related_chunk_id, relationship)`.

### Relationships & indexes
- `citations`: `uq_citation_ws_group`, `ix_citations_ws_doc`, + indexed `document_id`/`chunk_id`.
- `citation_references`: `uq_ref_unique`, `ix_refs_type (workspace_id, reference_type)`, indexed `citation_id`.
- `knowledge_references`: `uq_knowledge_edge`, `ix_knowledge_ws (workspace_id, citation_id)`.

### Scalability
The index is rebuilt **per workspace** (bounded by that workspace's citation count) and only when a
**count-based staleness check** detects drift. Denormalized `reference_count` + `ref_title` mean the
panel renders with zero extra joins. Co-occurrence edge materialization is capped
(`_MAX_CHUNKS_PER_ARTIFACT`, `_MAX_SAME_DOC_EDGES`) to prevent quadratic blow-up. Naive-UTC
timestamps match SQLite's tz-stripped reads (the convention adopted in Module 7).

---

## 5. Backend Architecture

Layered like every domain (`backend/app/citations/`):

- **`models.py`** — the 3 derived-index tables.
- **`indexer.py`** — the ONLY reader of the four source citation tables. `rebuild(workspace, owner)`
  does a deterministic delete+rebuild: collect live source rows (joining parents for labels +
  soft-delete filtering) → group into unified `Citation`s → write `CitationReference`s → compute
  `KnowledgeReference` edges (co-occurrence within an artifact + same-document neighbours).
- **`schemas.py`** — DTOs + query enums.
- **`errors.py`** — transport-agnostic errors.
- **`repository.py`** — all reads over the index: search/filter, references, knowledge edges (joined
  to neighbour citations), same-document lookup, document context, and workspace stats.
- **`explain.py`** — the pure, deterministic "why was this cited?" composer (§8).
- **`service.py`** — `ensure_synced` (the transparent staleness guard) + detail/related/explain/
  search/stats/by-chunk orchestration.
- **`api.py`** — authenticated read routes under `/workspaces/{id}/citations`.

**Evidence lookup:** `by_chunk` resolves a citation from a `(document_id, chunk_id)` — the bridge
that lets any AI-answer citation open the intelligence panel.

**Sync:** `ensure_synced` compares the live source-citation count to the indexed reference count (a
cheap 5-query check) and rebuilds only on drift — so every read is transparently fresh without the
caller thinking about indexing. A manual `POST /reindex` forces it.

**Error handling:** typed domain errors → `HTTPException` via `_handle`; workspace verified first.

---

## 6. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/citations.ts`** — the read client (search, detail, by-chunk, related, explain, stats, reindex).
- **`pages/KnowledgeExplorer.tsx`** — the hub (route `/workspace/:id/knowledge`): stats header, a
  search/filter toolbar (text, source type, confidence), a ranked citation list, and the
  `CitationPanel` as a detail pane. A `?chunk=` / `?citation=` query param deep-links the panel open.
- **`components/citations/CitationPanel.tsx`** — the reusable "source of truth" side panel:
  breadcrumbs (Workspace › Document › Page › Chunk), an evidence quote + confidence ring, metadata
  cards, "Open in PDF" (reuses Module 3), references grouped by type (each navigates to its
  artifact), related knowledge (backlinks — clicking one browses in-panel via a navigation stack),
  and the toggleable "Why cited?" explanation.

### State management & routing
No global store (consistent with the app). The explorer owns query/selection state with
`useState`/`useRef` + AbortController-guarded fetches; the panel owns its own fetch lifecycle and an
internal citation-id **navigation history** so exploring related evidence feels like browsing. The
route nests under the workspace; the panel is also openable from anywhere (chat citation cards carry
a 🔎 "explore" chip → `/knowledge?chunk=…`).

---

## 7. Retrieval Integration

Citation metadata flows through the **unchanged** production pipeline:

```
Retrieval (hybrid dense+BM25) → RRF fusion → Cross-encoder rerank → Duplicate detection →
Evidence ranking (→ confidence/evidence_score) → Context assembly → LLM →
[Modules 4–7 persist citations] → CitationIndexer → Citation Intelligence
```

The Phase-2 `structured_citations(evidence)` already captured `document_id, chunk_id, page_number,
citation_text, confidence (= evidence_score)` at generation time; Modules 4–7 persisted them. Module
8 **reads** those rows — it never re-runs retrieval and never forks the pipeline. `retrieval_score`
/`reranker_score` columns exist and are nullable: they weren't persisted historically, so the schema
is ready to capture them going forward without any behavioural change. This satisfies "expose
internal retrieval metadata without changing retrieval behaviour."

---

## 8. Explainability Design

`explain.py` composes a structured explanation **deterministically** — no second LLM call — because
LexiMind's retrieval path is fixed and known, and the relevant scores are stored on the citation.

- **Confidence** — banded (high ≥ 0.75, moderate ≥ 0.5, low) from `confidence`/`evidence_score`.
- **Retrieval / reranker scores** — surfaced when present (nullable for historical citations).
- **Why it was selected** — Phase-2 evidence ranking placed it among the top, directly-supporting
  chunks.
- **Why it outranked others** — RRF fused dense+keyword rankings, the cross-encoder reranker placed
  it above competitors, and duplicate detection kept it as the representative evidence.
- **Corroboration** — how many workspace assets reuse the same evidence (reinforces reliability).
- **Retrieval path** — the seven fixed Phase-1+2 stages, surfaced verbatim.

**Why deterministic:** it's instant, free, testable, and honest (it describes the *actual* pipeline).
An LLM-authored narrative can be layered on later behind the same `CitationExplanation` DTO — the
"future explainable AI" hook.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}/citations`. Reads
transparently refresh the index first.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| GET | `` | **Search/list** (keyword, document_id, page_number, reference_type, min_confidence, sort) | 200 `CitationListResponse` | |
| GET | `/stats` | Workspace citation statistics | 200 `CitationStats` | |
| GET | `/by-chunk?chunk_id=&document_id=` | **Resolve a citation from a chunk** (open panel from an answer) | 200 `CitationDetail` | 404 |
| GET | `/{id}` | **Citation detail** (metadata + references grouped + document context) | 200 `CitationDetail` | 404 |
| GET | `/{id}/related` | **Knowledge Explorer** payload (backlinks + same-document + type mix) | 200 `RelatedKnowledge` | 404 |
| GET | `/{id}/explain` | **"Why cited?"** explanation | 200 `CitationExplanation` | 404 |
| POST | `/reindex` | Force a full workspace rebuild | 200 `{ok, citations}` | |

**Example — detail:** `GET /citations/by-chunk?chunk_id=doc_x:0` →
`{id, citation_text, confidence, reference_count, references:[{reference_type, ref_title,
ref_parent_id}], references_by_type:{summary:1,note:1,flashcard:1,message:1}, document:{document_id,
citation_count, reference_count}}`.

**Example — related:** `GET /citations/{id}/related` →
`{related:[{chunk_id, relationship:"co_reference", strength, page_number, citation_text}],
references_by_type, same_document_citations:[…]}`.

Validation: `min_confidence` ∈ [0,1], pagination bounded (≤ 100), `reference_type` ∈ the enum. A
missing citation/chunk → 404; a foreign workspace → 404.

---

## 10. Performance Optimizations

- **Transparent, guarded sync:** reads rebuild the index only when a 5-query count check detects
  drift — an O(1)-ish no-op when nothing changed. No stale reads, no needless rebuilds.
- **Per-workspace scope:** rebuild cost is bounded by one workspace's citations, not the whole DB.
- **Denormalized panel data:** `reference_count`, `ref_title`, and navigation ids are stored on the
  index → the panel renders with **no joins**.
- **Capped edge materialization:** co-occurrence + same-document edges are bounded
  (`_MAX_CHUNKS_PER_ARTIFACT = 40`, `_MAX_SAME_DOC_EDGES = 10`) to keep rebuilds linear.
- **Search indexing:** citation text search is an indexed `LIKE`; `ix_citations_ws_doc` and
  `ix_refs_type` back the common filters; stats use grouped aggregates, not per-row scans.
- **No repeated metadata calc:** scores + reference counts are computed once at index time and
  stored; the explain composer is pure and cache-friendly.
- **Frontend:** the panel fetches detail + related in parallel; explanation is lazy (only on toggle);
  AbortController cancels superseded queries.

---

## 11. Testing

**Unit tests** (`test_citation_indexer.py`, 7) — the aggregation core:
- unifies the same chunk cited by a note AND a summary into one `Citation` with `reference_count=2`
  and `confidence = max`;
- references are typed + labelled (note_id set, `ref_title` = note title);
- co-occurrence edges created both ways between co-cited chunks;
- same-document edges when chunks don't co-occur;
- rebuild is idempotent (no duplication on re-run);
- staleness counts match sources before/after sync;
- soft-deleted parents contribute nothing.

**Integration tests** (`test_citation_api.py`, 11) — the full loop over HTTP:

```
Workspace → generate summary + note + flashcards + chat message (each citing doc_x chunks)
          → index aggregates across modules → detail (references grouped by all 4 types)
          → related (co-cited + same-document backlinks) → explain → search/filter → stats → reindex
```

Covers auth/scoping (401/404), cross-module aggregation, `by-chunk` detail unifying all four
reference types with `document` context, knowledge backlinks (co_reference to the co-cited chunk),
deterministic explanation (7-step retrieval path + corroboration factor), keyword/type/confidence
search, workspace stats, transparent re-sync after new citations, manual reindex, and 404s.

**Results:** 18 new tests pass. Full suite: **311 passed** (only `test_reranker`/`test_eval` skipped
— they need torch/sentence-transformers, a pre-existing environment constraint). **No regressions**
in Phase 1/2 or Modules 1–7. Frontend `tsc -b` + `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/citations/__init__.py` — package doc.
- `app/citations/models.py` — Citation / CitationReference / KnowledgeReference.
- `app/citations/indexer.py` — the aggregator (the only reader of the 4 source tables).
- `app/citations/schemas.py` — DTOs + enums.
- `app/citations/errors.py` — domain errors.
- `app/citations/repository.py` — all index reads + stats.
- `app/citations/explain.py` — deterministic explanation composer.
- `app/citations/service.py` — sync guard + orchestration.
- `app/citations/api.py` — the citations router.
- `tests/test_citation_{indexer,api}.py` — 18 tests.

### New frontend files
- `src/api/citations.ts`, `src/pages/KnowledgeExplorer.tsx`,
  `src/components/citations/CitationPanel.tsx`, `src/styles/citations.css`.

### Modified files (why)
- `app/db/base.py` — register citation models in `init_db()`.
- `app/main.py` — mount `citations_router`.
- `tests/conftest.py` — import citation models, mount the router (read-only; no fake engine needed).
- `src/App.tsx` — add the `/knowledge` route.
- `src/types.ts` — add the Citation Intelligence contracts.
- `src/main.tsx` — import `styles/citations.css`.
- `src/pages/WorkspaceDetail.tsx` — add the "🔎 Knowledge" entry point.
- `src/components/chat/CitationCard.tsx` + `src/components/chat/ChatMessage.tsx` +
  `src/pages/ChatWorkspace.tsx` — a 🔎 "explore" chip on chat citations → opens the panel at that chunk.

---

## 13. Future Compatibility

- **Knowledge Graph** — `KnowledgeReference` (typed edges + strength + `related_citation_id`) is
  already a graph; nodes are `Citation`s, edges are co_reference/same_document. Adding
  semantic-similarity edges (vector neighbours) or entity edges is additive.
- **Research Assistant** — the citation index is the evidence substrate: "gather everything cited
  about X across my workspace" is a search + related-knowledge traversal.
- **AI Tutor** — traceable, explainable evidence lets a tutor justify every claim and drill into
  sources the learner is unsure about.
- **Agentic reasoning** — an agent can walk citation → references → related citations to assemble a
  multi-hop evidence chain, with the explain layer as a built-in audit trail.
- **Cross-document reasoning** — `same_document` today; `related_document_id` on knowledge edges is
  ready for cross-document links, and the index is workspace-wide so multi-document evidence is a query.
- **Multimodal evidence** — the `Citation` node is content-agnostic; image/table/figure chunks slot
  in with the same reference + knowledge machinery.

---

## 14. Lessons Learned

**Architecture decisions**
- *Derive, don't duplicate.* The single most important call: make Module 8 an **index over** Modules
  4–7 rather than a new write path. Zero retrofit of existing modules, zero data duplication, and the
  intelligence is provably consistent because it's a deterministic function of the source rows.
- *Full rebuild + staleness guard beats incremental sync.* A per-workspace delete+rebuild is trivial
  to reason about and idempotent; a cheap count check keeps it from running when nothing changed.
  Incremental upserts would have added complexity and correctness risk for no user-visible gain.
- *Deterministic explainability.* Because the retrieval pipeline is fixed and known, a composed
  explanation is honest, instant, and testable — no LLM dependency, with an LLM upgrade path behind
  the same DTO.
- *Denormalize for the panel.* Storing `ref_title` + navigation ids on the reference row makes the
  panel a pure read — no join fan-out when rendering "used in 12 places".

**Tradeoffs**
- *Historical retrieval scores are absent.* Only `confidence` (evidence score) was persisted by
  Modules 4–7, so `retrieval_score`/`reranker_score` are null for existing citations. The columns +
  explain layer are ready; capturing them requires a small, forward-only change to the generation
  paths.
- *Lexical citation search.* `LIKE` over citation text now; semantic citation search is a natural
  drop-in behind the same search contract.
- *Co-occurrence, not semantics, for backlinks.* Related-knowledge edges are built from
  co-citation + same-document, which is precise but conservative; vector-similarity edges would
  broaden discovery (future).

**Known limitations**
- Reindex is synchronous on the request that detects drift (bounded per workspace; a background job
  is the scale-up path). No cross-workspace citation graph yet (schema is ready). Explain is
  template-composed, not model-authored.

**Future improvements**
- Capture retrieval/reranker scores at generation time; semantic citation search + similarity
  backlinks; a real graph view; background/incremental indexing; LLM-authored explanations; and
  wiring the explore panel into the summary/note/flashcard citation surfaces (chat is wired today).

---

### Success criteria — status

✅ Codebase audited · ✅ Citation domain implemented · ✅ Interactive citation panel · ✅ Knowledge
Explorer · ✅ Source traceability (answer→citation→chunk→page→document→workspace) · ✅ Explainable
citations · ✅ PDF viewer integration (reuses Module 3) · ✅ Search · ✅ Performance optimized ·
✅ Tests passing (18 new, 311 total) · ✅ No regressions in Phase 1/2 + Modules 1–7 · ✅ Documentation
complete (this file).
