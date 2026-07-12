# Phase 5 · Module 3 — Temporal Retrieval & Context Engine

> The evolution of LexiMind's **Phase-1 Retrieval Engine** and **Phase-2 Context Engine** for
> time-based media. Where document retrieval finds *pages*, this module retrieves **moments** — by
> time, speaker, topic, chapter, event, scene, frame, and exact timestamp — fuses and reranks those
> temporal signals, assembles a **timeline-aware context**, and builds an **adaptive,
> timestamp-preserving prompt** with temporal citations. It reuses (never rewrites) the existing
> retrieval/context infrastructure and is exposed as an **inspectable service** (no live LLM).

---

## 1. Module Overview

### Why temporal retrieval is needed
A recording's meaning is spread across a **timeline**. "What did the professor say about deadlocks?"
is not a page lookup — it is *"find the transcript span, attribute it to the speaker, and cite the
moment."* "What happened after the scheduling discussion?" requires **ordering**, not similarity.
Standard multimodal retrieval has no notion of time, speaker, or chronology, so it cannot answer these
faithfully or cite a timestamp.

### Document retrieval vs timeline retrieval
| | Document retrieval (Phase 1/4) | Timeline retrieval (this module) |
|---|---|---|
| Unit | chunk / page / asset | transcript segment / scene / chapter / event / frame |
| Anchor | `page_number`, bbox | `start_ms`, `end_ms`, speaker, scene, chapter |
| Query understanding | modality intent | **+ timestamp parsing, relative-order ("after…")** |
| Fusion | weighted RRF over modalities | **+ temporal adjacency** (answers cluster in time) |
| Rerank | cross-modal relevance | **+ speaker match + time-anchor proximity** |
| Context | evidence blocks | **chronological, timestamp-preserving blocks** |
| Citation | doc + page | **doc + [start,end] + speaker + scene/frame** |

### Overall architecture
Two additive packages, no rewrite of Phase 1/2/4:
- **`app/tintel/`** — *canonical* persistence for Chapters, Topics, and Timeline Events (foundational;
  a later Module 2 enriches these rows in place).
- **`app/tretrieval/`** — the Temporal Retrieval & Context engine that retrieves over the Module-1
  media tables + the tintel tables, fuses/reranks, and builds timeline-aware context + prompt.

---

## 2. Previous Architecture

Before this module, LexiMind could *process* audio/video (Phase 5 Module 1) into transcript segments,
speakers, scenes, frames, subtitles, and unified `MediaChunk`s (with `start_ms`/`end_ms`) — but there
was **no way to retrieve over them**. The Phase-4 multimodal retriever (`app/mmretrieval/`) searches
text/OCR/image/diagram/table/metadata and has **no temporal retriever, no timestamp query parsing, no
timeline fusion, and no time-preserving context**. Media Q&A was therefore impossible:

**Limitations:**
- No temporal query understanding (a timestamp or "after X" in the query was ignored).
- No retriever read the transcript/speaker/scene/frame tables.
- No chapters/topics/timeline-events existed at all (Module-2 territory).
- Context assembly had no time semantics — it could not order evidence chronologically or preserve
  timestamps through compression, so a cited answer could not point to a moment.

---

## 3. New Architecture

```
                         Query
                           │
                 Temporal Query Analysis         (timestamp parse · relative-order · modality intent)
                           │
   ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
Transcript  Speaker    Chapter    Topic      Event      Scene      Frame     Subtitle  Timestamp   (retrievers)
   └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                           │  (normalize each modality → [0,1])
                     Temporal Fusion              (weighted RRF/sum + temporal adjacency, dedup by key)
                           │
                    Temporal Reranking            (relevance + speaker/modality/time-proximity priors)
                           │
             Timeline-aware Context Engineering   (temporal dedup → budget → timestamp-preserving compress → chronological assembly)
                           │
              Adaptive, Timestamp-preserving Prompt   (structure adapts to query type; [n] + timestamp tags)
                           │
                   Temporal Citations             (doc + [start,end] + speaker + scene/frame)
                           │
                      (→ LLM, future)
```

**Data sources (all read-only, workspace-scoped):**
```
Module-1 media:  TranscriptSegment · Speaker · SpeakerTurn · Scene · MediaFrame · Subtitle
Module-3 tintel: Chapter · Topic · TimelineEvent   (canonical; auto-derived, Module-2-enrichable)
Reused pure helpers: mmretrieval.normalize · context.tokenizer · mmcontext.compression
```

---

## 4. Retrieval Pipeline

1. **Ensure intelligence** — `ensure_derived` (count-guarded) populates the canonical chapter/topic/
   event tables for any completed recording before searching (transparent; never re-derives).
2. **Temporal Query Analysis** (`intent.py`) — detects temporal modalities, parses explicit
   timestamps (`12:04`, `1:02:03`, `45 minutes`) into a ±60s anchor window, and detects relative
   order (`after`/`before` → timeline reasoning). Produces keywords, per-modality weights, primary
   intent, and a coarse `query_type`.
3. **Retrieval** (`retrievers.py`) — the activated subset of nine retrievers runs behind one
   `TemporalRetriever` protocol, each preserving exact timestamps + speaker/scene provenance and
   adding a time-anchor overlap bonus when a timestamp is present.
4. **Normalize** — each retriever's raw scores → [0,1] (reused `mmretrieval.normalize`).
5. **Temporal Fusion** (`fusion.py`) — weighted RRF/weighted-sum, dedup by stable `key` with full
   contribution accounting, **plus a temporal-adjacency bonus** nudging hits near the top moment.
6. **Temporal Reranking** (`rerank.py`) — lexical relevance blended with modality/speaker/time-proximity
   priors (lazy cross-encoder variant reuses the Phase-1 model).
7. **Timeline-aware Context** (`context.py`) — temporal dedup (overlap + same speaker + near-identical
   text), confidence-proportional token budget, **timestamp-preserving compression** (the timestamp
   lives on the block, so it always survives), chronological assembly.
8. **Prompt Assembly** (`prompt.py`) — adaptive structure per `query_type`; every evidence line tagged
   `[n]` + timestamp + speaker; the model is instructed to answer with timestamps.
9. **Timestamp Preservation** — every result and every citation carries `start_ms`/`end_ms`,
   `speaker`, `scene_id`/`frame_id`, plus the full score explanation (raw → normalized → fusion →
   rerank → final rank).

---

## 5. Backend Architecture

**`app/tintel/` (canonical persistence — foundational only):**
- `models.py` — `Chapter`, `Topic`, `TimelineEvent` (indexed by `(document_id, start_ms/timestamp_ms)`;
  each row carries `source` (`derived`→`model`), `confidence`, `pipeline_version` so a smarter pass is
  distinguishable). **This schema is canonical and stable — Module 2 upgrades rows, never replaces them.**
- `derivation.py` — pure, lightweight heuristics (scene-aligned chapters titled by keywords; keyword-run
  topics; merged chapter/scene/speaker/topic events). Explicitly **not** the full Module-2 algorithms.
- `repository.py` — SQL for the canonical tables + reads of Module-1 rows for derivation.
- `service.py` — `ensure_derived` (count-guarded, idempotent), `derive` (explicit), queries.
- `api.py` — chapters/topics/events + `derive`, nested under a media document.

**`app/tretrieval/` (retrieval + context):**
- `schemas.py` — `TemporalHit` (mutable, accumulates scores + preserves temporal provenance) + API DTOs.
- `intent.py` — temporal query analyzer (+ timestamp/order parsing). Pure.
- `retrievers.py` — nine retrievers behind one `TemporalRetriever` protocol; shared `lexical_score`,
  `_time_overlap_bonus`, `_finalize`; `TEMPORAL_RETRIEVERS` registry (plug-and-play).
- `fusion.py` / `rerank.py` — temporal fusion + reranker.
- `context.py` — timeline-aware assembly (reuses `context.tokenizer` + `mmcontext.compression`).
- `prompt.py` / `citations.py` — adaptive prompt + temporal citations.
- `repository.py` — workspace-scoped reads over media + tintel + `TemporalSearchLog` writes/stats.
- `service.py` — the orchestrator; `models.py` — `TemporalSearchLog` (observability).
- `api.py` — search + convenience routes + prompt/explain + stats/health.

**Caching / validation / errors:** `ensure_derived` is the caching guard (derive once, reuse). Domain
errors are transport-agnostic (`422` unknown modality, `404` workspace/media, `409` derive-before-
processed). Retrievers swallow per-retriever failures (one bad retriever never fails the search).

**Workers / background (Step 15):** derivation runs lazily via `ensure_derived` (no pipeline change to
Module 1); the `MediaChunk.embedding_status="pending"` queue remains the future seam for transcript/
timeline embedding indexing. Retrievers are structured for a session-per-retriever executor to
parallelize later without touching fusion/rerank.

---

## 6. Storage & Metadata Design

**Canonical tables (tintel):**
- `media_chapters` — `chapter_index, title, summary, keywords, start_ms, end_ms, source, confidence`.
- `media_topics` — `topic_index, label, keywords, start_ms, end_ms, salience, source`.
- `timeline_events` — `event_index, event_type, title, description, timestamp_ms, start_ms, end_ms,
  speaker_id, scene_id, chapter_id, source, confidence`.

**Indexes (timeline reads are range scans):** `(document_id, start_ms)` on chapters/topics,
`(document_id, timestamp_ms)` and `(document_id, event_type)` on events, `(workspace_id, document_id)`
everywhere. `temporal_search_logs` indexes `(workspace_id, created_at)`.

**Relationships:** every canonical row → `document_id` (a media `Document`) + `job_id` (provenance);
`timeline_events.chapter_id/scene_id/speaker_id` link back into chapters + Module-1 scenes/speakers.

**Scalability & extensibility:** rows are workspace/owner/document scoped and versioned via `source`/
`pipeline_version`, so Module 2 can re-derive and enrich in place. Adding a new retriever or a new
`event_type` is additive (a registry entry / a new string) — no schema migration.

---

## 7. Frontend Architecture

- **`api/temporal.ts`** — typed client (self-contained types) + `MODALITY_META` + `fmtTime`.
- **`pages/TemporalSearch.tsx`** (`/workspace/:id/temporal`) — natural-language search box, recording
  scope selector, example prompts, activated-intent chips, a **timeline bar**, timestamp result
  cards, a collapsible **timeline-aware prompt** viewer, and per-search timing.
- **`components/temporal/TimelineBar.tsx`** — results plotted on a shared time axis (color by modality,
  size by confidence).
- **`components/temporal/TimestampCard.tsx`** — modality badge, timespan, colored speaker, content,
  on-screen **frame preview**, and a **"Jump to {timestamp}"** link.
- **Timestamp navigation:** a citation/card jump routes to `/workspace/:id/media?doc=…&t=…`;
  `MediaWorkspace` reads the `doc` param and selects that recording (opens media → the transcript/
  frames are one tab away).
- **State management:** local React state + `AbortController`-scoped requests; no new dependency.
- **Routing:** lazy route in `App.tsx`; "⏱ Temporal Search" CTA on `WorkspaceDetail`.
- `styles/temporal.css` — theme-aware, reuses shared tokens.

---

## 8. Future Integration

- **Meeting / Lecture Intelligence** — chapters, topics, speaker turns, and timeline events are
  first-class canonical rows; summaries, action-items, and chapter navigation build directly on them.
- **Phase 5 Module 2 (Temporal Intelligence Engine)** — upgrades the *same* canonical rows: real
  semantic topic segmentation, AI chapter titles/summaries, event classification (`source` → `model`,
  richer `confidence`/`description`). No schema change; Module-3 retrieval improves for free.
- **Research Agents / Autonomous AI** — the `explain` endpoint + `TemporalHit` score trail give agents
  a transparent, timestamp-anchored evidence graph to reason over.
- **Knowledge Graph** — speakers ↔ topics ↔ chapters ↔ events are ready to become nodes/edges.
- **Enterprise Search** — workspace-scoped temporal search across many recordings, with per-recording
  scoping and observability metrics feeding future dashboards.
- **Live media chat** — `build_prompt` already emits an LLM-ready, citation-tagged prompt; wiring it to
  `answer_service.complete` turns this inspectable service into media Q&A.

---

## 9. API Documentation

All routes authenticated (bearer) + workspace-scoped.

### Temporal Intelligence (canonical persistence) — `/workspaces/{ws}/media/{doc}`
| Method | Path | Body/Query | Response | Errors |
|---|---|---|---|---|
| GET | `/chapters` | — | `ChapterOut[]` (auto-derives) | 404 |
| GET | `/topics` | — | `TopicOut[]` | 404 |
| GET | `/events` | `?event_type=` | `TimelineEventOut[]` | 404 |
| POST | `/temporal-intelligence/derive` | `{force?}` | `{document_id,chapters,topics,events}` | 404, 409 (not processed) |

### Temporal Retrieval & Context — `/workspaces/{ws}/temporal`
| Method | Path | Body/Query | Response | Errors |
|---|---|---|---|---|
| POST | `/search` | `TemporalSearchRequest` | `TemporalSearchResponse` (results + prompt + citations + explanation) | 404, 422 (bad modality) |
| GET | `/timeline` `/speakers` `/chapters` `/scenes` `/events` | `?q=&top_k=&document_id=` | `TemporalSearchResponse` | 404 |
| POST | `/prompt` | `TemporalSearchRequest` | `PromptPreviewResponse{query_type,prompt,system_prompt,citations,token_estimate}` | 404 |
| POST | `/explain` | `TemporalSearchRequest` | `ExplainResponse{analysis,results}` | 404 |
| GET | `/stats` | — | `{searches,avg_latency_ms,modality_usage,indexed,recent_queries}` | 404 |
| GET | `/health` | — | `{status,retrievers,indexed}` | 404 |

**`TemporalSearchRequest`:** `query` (1..1000), `modalities?`, `document_id?`, `top_k` (1..50),
`per_retriever_k` (1..100), `fusion` (`rrf`|`weighted_sum`), `normalize` (`minmax`|`zscore`),
`rerank`, `build_context`, `explain`.

**Every result** carries `start_ms`, `end_ms`, `timespan`, `speaker_label`, `scene_id`, `frame_id`,
`confidence`, `final_rank`, and (when `explain`) the full `raw→normalized→fusion→rerank` trail.

**Example:**
```
POST /workspaces/ws_1/temporal/search
{ "query": "what did the professor say about deadlocks at 12:04?" }
→ intents: ["speaker","timestamp","topic","transcript"], primary: "timestamp",
  time_filter: { anchor_ms: 724000 },
  results: [ { modality:"transcript", timespan:"12:00–12:10", speaker_label:"SPEAKER_00",
               content:"…deadlocks occur when…", final_rank:1 }, … ],
  prompt: "…[1] (Transcript 12:00–12:10 · SPEAKER_00) …\nQuestion: …",
  citations: [ { index:1, timespan:"12:00–12:10", speaker_label:"SPEAKER_00" } ]
```

---

## 10. Performance Optimizations

- **Derive-once caching** — `ensure_derived` is count-guarded; the canonical tables are built on the
  first search of a recording and reused thereafter (never re-derived, never clobbers Module-2 rows).
- **Bounded, DB-lexical retrievers** — deterministic and faiss/torch-free; each retriever is `top-k`
  capped (`per_retriever_k`) and its candidate reads are `limit`-bounded (large-lecture safe).
- **Parallel-ready** — retrievers are independent; the orchestrator is structured for a
  session-per-retriever executor without touching fusion/rerank. Per-retriever latency is always measured.
- **Timestamp-preserving compression** — reuses the Phase-4 extractive compressor to fit more evidence
  in budget; timestamps live on the block, so compression never costs a citation.
- **Confidence-proportional budgeting** — a hard total token ceiling split across blocks by confidence.
- **Incremental / future embedding** — the `embedding_status="pending"` queue is the seam for future
  transcript/timeline vector indexing; nothing is embedded now (no FAISS work on the request path).
- **Observability** — `TemporalSearchLog` records analysis/fusion/rerank/context/prompt latencies +
  per-retriever counts for Step-14 dashboards.

---

## 11. Testing

Everything runs **offline** (no ffmpeg/whisper/faiss/torch) via the media `FakeMediaEngine`/`InlineRunner`.

**Unit (`tests/test_tretrieval_unit.py`, 15 tests):** tintel derivation (chapters scene-aligned +
fixed-window fallback, topic grouping, event merge/order), query analysis (timestamp formats, order
detection, modality intent, query-type), fusion (cross-modal merge + temporal adjacency), reranking
(speaker prior + blend), timeline context (temporal dedup, chronological assembly, timestamp
preservation), adaptive prompt, and temporal citations.

**Integration (`tests/test_tretrieval_api.py`, 14 tests):** full lifecycle over HTTP —
```
upload media → process (inline) → derive chapters/topics/events → temporal search
   → timestamped results + timeline prompt + citations → timestamp/speaker/timeline queries
   → prompt preview → explanation → stats/health
```
plus auto-derive-on-read, event-type filter, derive-conflict (409) on a non-media doc, unknown-modality
(422), document-scoped search, and auth.

**Results:** 29 new tests pass. **Full suite: 487 passed** (458 prior + 29 new), `test_reranker`/
`test_eval` excluded per project convention (torch). **Zero regressions** across Phases 1–4 and Phase 5
Modules 1. Frontend `tsc -b` clean; `vite build` succeeds (`TemporalSearch` chunk emitted).

---

## 12. File Changes Summary

### New — backend `app/tintel/` (canonical temporal-intelligence persistence)
`__init__.py`, `models.py` (Chapter/Topic/TimelineEvent), `derivation.py` (lightweight heuristics),
`repository.py`, `service.py` (ensure_derived + derive), `schemas.py`, `errors.py`, `api.py`.

### New — backend `app/tretrieval/` (temporal retrieval & context)
`__init__.py`, `models.py` (TemporalSearchLog), `schemas.py` (TemporalHit + DTOs), `intent.py`,
`retrievers.py` (9 retrievers), `fusion.py`, `rerank.py`, `context.py`, `prompt.py`, `citations.py`,
`repository.py`, `service.py`, `errors.py`, `api.py`.

### New — tests & frontend & docs
`tests/test_tretrieval_unit.py`, `tests/test_tretrieval_api.py`,
`frontend/.../api/temporal.ts`, `frontend/.../pages/TemporalSearch.tsx`,
`frontend/.../components/temporal/{TimelineBar,TimestampCard}.tsx`,
`frontend/.../styles/temporal.css`, `phase5_module3.md`.

### Modified (registration/wiring + one deep-link — no behavior change)
| File | Change |
|---|---|
| `backend/app/db/base.py` | register tintel + tretrieval models in `init_db()` |
| `backend/app/main.py` | mount `tintel_router` + `tretrieval_router` |
| `backend/tests/conftest.py` | register models + mount both routers |
| `frontend/.../App.tsx` | lazy `/workspace/:id/temporal` route |
| `frontend/.../pages/WorkspaceDetail.tsx` | "⏱ Temporal Search" CTA |
| `frontend/.../pages/MediaWorkspace.tsx` | honor `?doc=` deep-link (open media from a citation) |

Nothing in Phase 1/2/3/4 or Phase 5 Module 1 was modified in behavior — the retrieval normalizer,
tokenizer, and compressor are **imported and reused**, not changed.

---

## 13. Lessons Learned

**Architecture decisions**
- *Mirror `mmretrieval` + `mmcontext`, don't fork them.* The `Retriever` protocol / `RetrievalHit` /
  `fuse` / reranker / intent shapes generalized to time with minimal new code; the normalizer,
  tokenizer, and compressor are reused verbatim. Temporal retrieval reads like multimodal retrieval —
  because it is the same pattern with time added.
- *Make Chapter/Topic/Event the canonical schema now, populate cheaply.* Rather than stub three dead
  retrievers or build all of Module 2, the canonical tables were created with `source`/`confidence`/
  `pipeline_version` and populated by lightweight derivation. Module 2 enriches the same rows — the
  storage layer is settled and stable from day one.
- *Derive lazily via a count-guard.* `ensure_derived` (borrowed from `citations.ensure_synced`) keeps
  Module-1's pipeline untouched while guaranteeing chapter/topic/event data exists at search time.
- *Preserve time on the block, not in the text.* Timestamps survive compression because they live on
  the `ContextBlock`/citation, so an aggressive compressor can never cost a citation its moment.

**Tradeoffs**
- Retrievers score lexically (bounded, deterministic, testable) — the same trade `mmretrieval` makes;
  a production run swaps the lazy cross-encoder reranker in behind the same interface. Semantic
  transcript embeddings are deferred to the `embedding_status="pending"` queue.
- The timestamp anchor uses a fixed ±60s window; good enough for "around 12:04" but a future version
  could size the window from speech-rate or scene length.

**Known limitations**
- Derived chapters/topics/events are a *baseline* (keyword-level), not semantic — Module 2's job.
- The service is inspectable only: it builds the LLM-ready prompt but does not call a model yet.
- Retrievers run sequentially (SQLite session constraint); parallelization is structured-for but not
  enabled.

**Future improvements**
- Wire `build_prompt` into `answer_service.complete` for live, timestamp-citing media Q&A.
- Embed transcript/timeline chunks and add a dense temporal retriever behind the same protocol.
- Parallel session-per-retriever execution; adaptive anchor windows; Module-2 enrichment of the
  canonical rows.
