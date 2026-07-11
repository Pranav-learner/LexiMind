# Phase 3 — Module 9: Knowledge Dashboard & Analytics Platform

> Status: ✅ Complete. Backend (9 files, an aggregation + widget-registry + cache design) + frontend
> (5 files incl. dependency-free SVG charts) + 3 test suites (18 new tests, all passing; **329 total
> tests green** with no regressions across Phase 1/2 and Modules 1–8).

---

## 1. Module Overview

**Why knowledge analytics matter.** After eight modules a LexiMind workspace holds documents, chats,
summaries, notes, flashcards, citations, and learning history — but that value was invisible in
aggregate. A knowledge worker needs to see, at a glance, *what they have*, *what they've learned*,
*what needs revision*, and *how the AI is performing*. This module is the **executive dashboard**:
the analytics home of every workspace.

**How dashboards improve productivity.** They collapse a dozen scattered screens into one. Instead
of opening each module to check state, the user opens the dashboard and instantly sees documents,
questions asked, mastery, streaks, due reviews, storage, and recent activity — plus one-click quick
actions to act on any of it. Less navigation, faster decisions.

**Raw data vs actionable insights.** "You have 20 flashcards" is data. "75% of your flashcards are
mastered — but you haven't reviewed *Operating Systems* in 12 days" is an **insight**: it interprets
the data and tells you what to do. This module ships both — statistics *and* a data-driven
recommendation engine that turns numbers into next actions.

Think: **GitHub contributions + Notion dashboard + Obsidian statistics + Google Analytics + learning
analytics**, for knowledge.

---

## 2. Previous Architecture (how users monitored progress before)

Monitoring was **per-module and shallow**:
- The workspace card showed five denormalized counters (documents/chats/notes/flashcards/summaries).
- The flashcards dashboard had its own learning analytics (streak, accuracy, activity chart).
- The citation explorer had citation stats.
- Everything else (AI usage, retrieval performance, per-document analytics, cross-module activity,
  knowledge growth, recommendations) was **not surfaced anywhere**.

**Limitations:** no single pane of glass; no AI-usage or retrieval visibility; no per-document
analytics; no activity timeline; no recommendations; and each module recomputed its own numbers with
no shared caching. The user could *use* the platform but couldn't *understand* their knowledge base.

---

## 3. New Architecture

```
   Workspace (documents · chat · summaries · notes · flashcards · citations · reading)
        │  (each module owns its rows)
        ▼
   ┌──────────────  Analytics Engine  ──────────────┐
   │  Widget Registry (@widget):                     │
   │   knowledge · ai_usage · learning · documents · │
   │   retrieval · activity · charts                 │
   │            + Recommendation Engine (insights)   │
   └───────────────────────┬──────────────────────────┘
                           ▼
        Signature-based Cache  (AnalyticsSnapshot)   ← recompute only on data change / TTL
                           ▼
   ┌──────────────  Dashboard Widgets  ──────────────┐
   │  Overview cards · Insights · Charts (SVG) ·      │
   │  Heatmap · Timeline · Quick actions              │
   └──────────────────────────────────────────────────┘
```

Every widget only **reads** other modules' rows; nothing is mutated and the retrieval pipeline is
never touched. The **widget registry** makes the engine extensible: a future module adds a dashboard
widget by decorating a function — no existing code changes.

---

## 4. Database & Aggregation Design

**One new table** (`backend/app/analytics/models.py`): `AnalyticsSnapshot` — a per-(workspace,
section) cache of a computed widget's JSON payload: `id, workspace_id, owner_id, section (widget
key), signature (data fingerprint), payload (JSON), computed_at`. **Unique** `(workspace_id,
section)`; indexed by `workspace_id`.

**Aggregation strategy.** Each widget is a function `(AggContext) -> JSON-safe dict` in
`aggregators.py`. It reads the source modules with scoped SQL aggregates (SUM/AVG/COUNT/GROUP BY) —
e.g. knowledge sums `page_count`/`chunk_count`/`file_size` over `documents`; ai_usage averages
`latency_ms`/`retrieval_ms`/`context_size`/`token_usage` over assistant `messages`; learning reuses
`FlashcardRepository.analytics`; document analytics links summaries/notes/flashcards by
`document_id` and citations by `vector_document_id`.

**Caching.** `AnalyticsService.section()` returns the cached payload when the workspace's
**signature** (a cheap fingerprint = denormalized counters + a few COUNTs for messages/reviews/
citations/docs/notes/summaries) is unchanged **and** the snapshot is within a 300 s TTL; otherwise it
recomputes and upserts. So aggregation runs only when data actually changed (or every 5 min for
time-relative metrics like streaks) — never on every request.

**Indexes.** The cache table is indexed by workspace; the source tables were already indexed by the
owning modules (workspace_id everywhere, plus the specific indexes each module added). No new source
indexes were needed.

**Scalability.** Aggregation is per-workspace (bounded), guarded by the signature, and cached. On a
large workspace the first load computes once; subsequent loads are a single cache read + a ~7-COUNT
signature check.

---

## 5. Backend Architecture

Layered like every domain (`backend/app/analytics/`):

- **`models.py`** — `AnalyticsSnapshot` cache table.
- **`aggregators.py`** — the **statistics/analytics engine**: the `@widget`-decorated registry of
  independently-extensible widgets (knowledge, ai_usage, learning, documents, retrieval, activity,
  charts), each a read-only aggregate over other modules.
- **`insights.py`** — the **recommendation engine**: `generate_insights(...)` composes ranked,
  actionable recommendations from the computed sections + a cheap stale-deck query. Deterministic and
  data-driven (not hard-coded strings).
- **`schemas.py`** — the visualization DTOs (the frontend contract).
- **`errors.py`** — transport-agnostic domain errors.
- **`repository.py`** — the **cache layer** + the cheap **signature**.
- **`service.py`** — caching orchestration (`section` compute-or-cache, `dashboard` assembly,
  `insights`, `documents`, `refresh`).
- **`api.py`** — authenticated read routes under `/workspaces/{id}/dashboard`.

**Statistics engine / recommendation engine / caching** are cleanly separated (aggregators vs
insights vs repository+service). **Validation** is via bounded query params; **error handling** maps
typed errors → HTTP; workspace ownership is verified before any work.

**Background jobs.** None required — the signature+TTL cache achieves "don't recompute on every
request" without a scheduler. A background refresher is a trivial future add (the cache is already
the seam).

---

## 6. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/analytics.ts`** — the read client (dashboard, per-section, activity, insights, documents,
  refresh).
- **`pages/Dashboard.tsx`** — the analytics home (route `/workspace/:id/dashboard`): quick-action
  rail, overview stat cards, insights, a charts grid, an AI-usage + retrieval panel, and a filterable
  activity timeline. One `/dashboard` round-trip populates everything.
- **`components/dashboard/Charts.tsx`** — dependency-free SVG chart primitives: `LineChart` (area +
  line + hover dots), `DonutChart` (segments + legend), `Heatmap` (GitHub-style calendar). Responsive
  (viewBox-scaled), accessible (`role`/`aria` + `<title>` tooltips), theme-aware (inherit CSS vars).

**State management** — no global store (consistent with the app); the page fetches once with an
AbortController-guarded effect and derives chart series with `useMemo`. **Routing** nests under the
workspace; WorkspaceDetail gets a prominent "📊 Open Dashboard" CTA. **Responsive behavior** — the
grids are `auto-fit`/`minmax`; the two-column panels collapse and the heatmap shrinks on small
screens; light/dark come free from the shared tokens.

---

## 7. AI Integration

The dashboard **reuses** analytics already produced — no duplicated logic:

- **Retrieval / Context Engineering** → `retrieval` widget reads `app.core.config.settings` (pipeline
  config: hybrid/BM25/dense/RRF/reranker/compression, top-k, window) + runtime latency/context
  aggregates from `messages`. It never imports the faiss pipeline and never changes its behaviour.
- **Chat** → ai_usage (questions, conversations, messages, avg times/tokens, model usage).
- **Summaries / Notes / Flashcards** → counts + per-document links; learning reuses
  `FlashcardRepository.analytics` verbatim.
- **Citation Intelligence** → citation usage + per-document citation/question frequency (counted from
  the source citation tables, index-independent).

No metric is recomputed in a way another module already owns — the analytics engine *consumes*.

---

## 8. Visualization Design

**Chart selection** matches the data: **line** for time series (activity, AI usage, knowledge
growth), **donut** for part-of-whole (workspace distribution, flashcard progress), **heatmap** for
daily-intensity calendars, and **stat cards / metric rows** for scalars. **Dashboard layout** is a
responsive grid — a quick-action rail, an 8-card overview strip, insights, a charts grid (the
heatmap spans full width), a two-column AI/retrieval panel, and a timeline.

**Chart-library choice (documented):** a **dependency-free inline-SVG** approach rather than a
heavyweight charting library — consistent with the markdown-editor / CSS-chart decisions in earlier
modules. Rationale: zero new npm dependencies (no offline/supply-chain risk, build stays green),
full control over accessibility and theming, and small bundle size. The components take generic
`points` props, so a production charting lib can replace them later with no page changes.
**Accessibility:** every chart has `role="img"` + an `aria-label`, and data points carry `<title>`
tooltips. **Performance:** SVGs are static (no per-frame JS); series are memoized. **Extensibility:**
add a backend widget → surface it with an existing chart primitive.

---

## 9. API Documentation

All routes authenticated + workspace-scoped, read-only, under `/workspaces/{workspace_id}/dashboard`.
Every section is cached (signature + TTL).

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `` | **Full dashboard** (knowledge, ai_usage, learning, retrieval, charts, activity, insights) | 200 object |
| GET | `/knowledge` | Knowledge statistics | 200 `KnowledgeStats` |
| GET | `/ai-usage` | AI usage analytics | 200 `AiUsage` |
| GET | `/learning` | Learning analytics | 200 `LearningStats` |
| GET | `/retrieval` | Retrieval/context config + runtime | 200 `RetrievalAnalytics` |
| GET | `/charts` | Chart series (line/donut/heatmap) | 200 `{series:[…]}` |
| GET | `/activity?type=&limit=` | Activity timeline (filterable) | 200 `{items:[…]}` |
| GET | `/insights` | AI recommendations | 200 `{items:[…]}` |
| GET | `/documents` | Per-document analytics list | 200 `{items:[…]}` |
| GET | `/documents/{id}` | One document's analytics | 200 `DocumentAnalytics` / 404 |
| POST | `/refresh` | Bust the cache + return a fresh dashboard | 200 object |

**Example — dashboard:** `GET /dashboard` →
`{knowledge:{documents,pages,chunks,storage_bytes,index_health,…}, ai_usage:{questions_asked,
avg_response_time_ms,…}, learning:{study_streak_days,retention,mastered_cards,…}, retrieval:{…},
charts:{series:[{key,kind,points}]}, activity:{items:[…]}, insights:[{severity,title,message,
action_route}]}`.

Validation: `activity.limit` ∈ [1,100]; unknown document → 404; foreign workspace → 404.

---

## 10. Performance Optimizations

- **Signature-guarded cache:** the expensive aggregation runs only when the workspace's cheap
  COUNT-fingerprint changes or the 300 s TTL lapses. Repeat loads are one cache read + ~7 COUNTs.
- **Per-widget caching:** sections are cached independently, so a change that only affects one widget
  doesn't force recomputing the rest (the shared signature is computed once per request).
- **One round-trip:** the dashboard endpoint assembles all sections server-side; the SPA makes a
  single request.
- **Aggregate SQL:** SUM/AVG/COUNT/GROUP BY push work into the DB rather than materializing rows.
- **Incremental-ready:** `refresh` busts the cache explicitly; a background refresher can warm it
  without any interface change.
- **Frontend:** static SVG charts (no chart-lib runtime), memoized series, AbortController-guarded
  fetch. Database access uses the indexes the owning modules already declared.

---

## 11. Testing

**Unit tests**
- `test_analytics_insights.py` (4) — the recommendation engine: every rule fires on crafted sections
  (streak, due, mastery %, retention warning, coverage, top-source, top-asked, milestone), warnings
  rank first, and rules correctly *don't* fire when there's no data; actions carry routes.
- `test_analytics_service.py` (5) — caching: a section computes + writes a snapshot; the cache
  returns the same until the **signature changes** (add a note → recompute); the signature reflects
  data; `dashboard()` assembles all sections; `refresh()` busts the cache.

**Integration tests** (`test_analytics_api.py`, 9) — the full loop over HTTP:

```
Workspace → upload document → chat → generate summary + note → generate flashcards → review cards
          → GET /dashboard aggregates everything → sections → per-document analytics → activity
          → insights → cache invalidates on a new upload → refresh
```

Covers auth/scoping (401/404), full-dashboard aggregation (documents/chunks, questions/conversations,
summaries/notes/flashcards, cards reviewed, chart series, activity, insights), empty-workspace
defaults, each section endpoint, per-document analytics (+ 404), activity timeline + type filter,
insight generation, and **transparent cache invalidation** on a second upload + manual refresh.

**Results:** 18 new tests pass. Full suite: **329 passed** (only `test_reranker`/`test_eval` skipped
— they need torch/sentence-transformers, a pre-existing environment constraint). **No regressions**
in Phase 1/2 or Modules 1–8. Frontend `tsc -b` + `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/analytics/__init__.py` — package doc.
- `app/analytics/models.py` — `AnalyticsSnapshot` cache table.
- `app/analytics/aggregators.py` — the widget registry + statistics/analytics engine.
- `app/analytics/insights.py` — the recommendation engine.
- `app/analytics/schemas.py` — visualization DTOs.
- `app/analytics/errors.py` — domain errors.
- `app/analytics/repository.py` — cache layer + signature.
- `app/analytics/service.py` — caching orchestration.
- `app/analytics/api.py` — the dashboard router.
- `tests/test_analytics_{insights,service,api}.py` — 18 tests.

### New frontend files
- `src/api/analytics.ts`, `src/pages/Dashboard.tsx`,
  `src/components/dashboard/Charts.tsx`, `src/styles/dashboard.css`.

### Modified files (why)
- `app/db/base.py` — register the analytics model in `init_db()`.
- `app/main.py` — mount `analytics_router`.
- `tests/conftest.py` — import the analytics model + mount the router (read-only; no fake engine).
- `src/App.tsx` — add the `/dashboard` route.
- `src/types.ts` — add the dashboard/analytics contracts.
- `src/main.tsx` — import `styles/dashboard.css`.
- `src/pages/WorkspaceDetail.tsx` — add the prominent "📊 Open Dashboard" CTA.

---

## 13. Future Compatibility

- **Knowledge Graph** — the dashboard already surfaces citation/knowledge counts; a graph widget
  registers via `@widget` and reads Module 8's `KnowledgeReference` edges with no engine change.
- **AI Tutor** — learning analytics + per-document mastery + recommendations are exactly the signals
  a tutor consumes to plan a study session.
- **Research Assistant** — knowledge stats + document analytics + top-cited sources are a ready
  research-surface; "what have I got on X and where is it weakest?" is a widget.
- **Agentic workflows** — the recommendation engine is the seed: today it *suggests* ("review X");
  an agent can *act* on the same signals. `_RULES` is a registration point for agent-authored rules.
- **Collaborative analytics** — snapshots are per (workspace, owner); adding a member dimension makes
  them per-team. The signature/cache design extends unchanged.
- **Enterprise dashboards** — cross-workspace roll-ups are an aggregation over the same widgets; the
  cache table already keys by workspace so a portfolio view is a fan-out + merge.

---

## 14. Lessons Learned

**Architecture decisions**
- *Widget registry over a monolith.* Making each metric group a registered `@widget` function keeps
  the engine open for extension (new modules add widgets) and closed for modification — the exact
  brief. It also made caching uniform (every widget caches the same way).
- *Signature-based cache beats a background job.* A cheap COUNT-fingerprint + short TTL delivers
  "don't recompute on every request" with zero infrastructure — no scheduler, no staleness bugs,
  correct by construction. The cache is a clean seam for a future warmer.
- *Aggregate, never duplicate.* Reusing `FlashcardRepository.analytics`, the citation source tables,
  and `settings` config meant the dashboard is consistent with the modules that own the data — one
  source of truth, surfaced many ways.
- *Deterministic insights.* Data-driven rules (not hard-coded messages, not an LLM call) are instant,
  testable, and honest; an LLM narrative layer can sit on top later.

**Tradeoffs**
- *Some metrics are proxies.* "Retrieval frequency" ≈ citation count (we don't log every retrieval);
  "reading minutes" uses note reading-time; "topics" are heuristic name tokens. All are the best
  *available* signals and are documented as such — richer telemetry is a forward-only add.
- *TTL vs freshness for time-relative metrics.* "Days since review" can lag by up to the 300 s TTL;
  acceptable for a dashboard, and the signature covers all data-driven changes immediately.
- *SVG charts vs a charting library.* Traded rich interactions for zero dependencies + full theming
  control; the generic `points` props keep the upgrade path open.

**Known limitations**
- No event-sourced activity log — the timeline is derived from `created_at`s (so "citation opened"
  isn't tracked; upload/generate/review/start are). No cross-workspace roll-up yet. Recall/precision/
  MRR are eval-harness-only (shown as a note), not per-workspace runtime.

**Future improvements**
- A lightweight event table for true activity (incl. citation-open + searches); a background cache
  warmer; per-query retrieval-score capture to power live retrieval quality charts; cross-workspace
  and team dashboards; LLM-authored insight narratives; and CSV/PDF dashboard export.

---

### Success criteria — status

✅ Codebase audited · ✅ Analytics Engine (widget registry) · ✅ Knowledge Dashboard · ✅ Learning
Analytics · ✅ Document Analytics · ✅ Retrieval Analytics (integrated, read-only) · ✅ AI Insights
(recommendation engine) · ✅ Activity Timeline (filterable) · ✅ Professional visualizations (SVG
charts + heatmap) · ✅ Dashboard performance optimized (signature cache) · ✅ Tests passing (18 new,
329 total) · ✅ No regressions in Phase 1/2 + Modules 1–8 · ✅ Documentation complete (this file).
