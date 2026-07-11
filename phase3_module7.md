# Phase 3 — Module 7: AI Flashcards & Active Recall Learning Engine

> Status: ✅ Complete. Backend (11 files incl. a pure SM-2 scheduler) + frontend (13 files) + 4 test
> suites (42 new tests, all passing; **293 total tests green** with no regressions across Phase 1/2
> and Modules 1–6).

---

## 1. Module Overview

**Why active recall matters.** Reading and highlighting feel productive but produce *recognition*,
not *recall* — you recognize the material when you see it again, yet can't reproduce it in an exam
or conversation. **Active recall** (retrieving an answer from memory before checking it) is one of
the most robustly evidenced learning techniques: the *testing effect* shows that the act of
retrieval itself strengthens memory far more than re-reading.

**Passive reading vs flashcard learning.** A summary or a note is consumed passively — the brain
does no retrieval work. A flashcard forces retrieval: you see a prompt, generate the answer from
memory, then verify. That effortful retrieval is what builds durable memory.

**Why spaced repetition improves long-term retention.** The *spacing effect* shows that reviews
spread over increasing intervals beat massed cramming. But which interval? The **forgetting curve**
says memory decays predictably; the optimal moment to review is *just before you'd forget*. A
Spaced-Repetition System (SRS) schedules each card individually to hit that moment — expanding the
interval every time you succeed and contracting it when you fail. The result: maximal retention for
minimal review time. This module makes LexiMind a genuine learning platform, not just a document
assistant.

---

## 2. Previous Architecture (how LexiMind supported learning before)

Before Module 7, LexiMind supported *knowledge management* but not *learning*:

- **Documents/PDF viewer** — read + navigate + cite.
- **Chat** — ask questions, get grounded answers.
- **Summaries** — condense material (passive consumption).
- **Notes** — capture + edit knowledge (authoring, still passive recall-wise).

The workspace already reserved a `flashcard_count` counter and the PDF viewer had **stubbed**
"Flashcard"/"Generate Flashcard" selection actions (`live: false`, "coming soon") — the platform was
built in anticipation of this module.

**Limitations:** nothing tested the user; nothing scheduled review; no retention measurement; no way
to turn the accumulated documents/notes/summaries/chats into study material. Knowledge went *in* but
there was no mechanism to make it *stick*.

---

## 3. New Architecture

```
   Documents / Notes / Summaries / Chat / PDF selection
                        │
                        ▼
   ┌──────────────  Retrieval (Phase 1)  ──────────────┐
   │  Query Analysis → Hybrid (dense+BM25) → RRF →      │
   │  Reranker → dedup → evidence ranking               │
   └───────────────────────┬────────────────────────────┘
                           ▼
        Context Engineering (Phase 2): compression + assembly
                           │
                           ▼
            AI Flashcard Generation (structured, parsed)
                           │
                           ▼
              Citation Validation & Preservation
                           │
                           ▼
     ┌──────────────  Deck Management  ──────────────┐
     │  Deck ← Flashcards (+ SRS state) ← Citations   │
     └───────────────────────┬────────────────────────┘
                             ▼
        Spaced Repetition (SM-2): schedule(rating) → next_review_at
                             │  ▲ FlashcardReview log
                             ▼  │
                    Learning Analytics
      (accuracy · retention · streak · mastery · daily activity)
```

The AI path **reuses the production Retrieval + Context Engineering pipelines verbatim** (via
`PipelineFlashcardEngine`) — no second RAG stack. The SRS is a pure function; the review log feeds
analytics.

---

## 4. Database Design

Four new tables (SQLite; additive `create_all`). Defined in `backend/app/flashcards/models.py`.

### `decks`
Container + async-generation lifecycle. Columns: `id, workspace_id, owner_id, name, description,
color, icon`; provenance/scope `scope (manual|document|multi|workspace), document_id,
document_ids(JSON), note_id, summary_id, conversation_id, subject, card_type_pref, target_count`;
lifecycle `status, progress, stage, error`; `created_by, card_count (denormalized), is_archived,
is_public (future shared decks)`; AI telemetry `model_name, token_usage, generation_ms`;
`deleted_at, created_at, updated_at`.

### `flashcards`
The learning asset + its **full SRS state**. Content: `front, back, hint, card_type
(basic|definition|cloze|truefalse), extra(JSON), media(JSON, future), difficulty`. Organization:
`status (active|suspended|archived), is_favorite`. SRS (outputs of `scheduler.py`): `learning_stage
(new|learning|review|relearning), ease_factor, interval_days, repetitions, review_count,
lapse_count, correct_count, mastery_score, last_reviewed_at, next_review_at`. Plus back-links
(`deck_id, document_id, note_id, summary_id, conversation_id`), `citation_count`, soft-delete +
timestamps.

### `flashcard_citations`
Grounded provenance: `flashcard_id, document_id (vector id), chunk_id, page_number, workspace_id,
citation_text, confidence`.

### `flashcard_reviews`
Immutable review log (powers analytics): `flashcard_id, deck_id, workspace_id, owner_id, rating,
quality_score, response_time_ms, was_correct, prev_interval, scheduled_interval, ease_factor,
review_date`.

### Relationships & indexes
- `decks`: `ix_decks_owner_ws`, `ix_decks_ws_updated`.
- `flashcards`: `ix_flashcards_deck_status`, **`ix_flashcards_ws_due (workspace_id, status,
  next_review_at)`** — the review-queue query — and `ix_flashcards_owner_ws`.
- `flashcard_reviews`: `ix_reviews_ws_date`, `ix_reviews_card_date` for analytics.

### Scalability
`next_review_at` (nullable = never-seen "new" card) makes the review queue a single indexed range
scan (`next_review_at <= now`). Denormalized counters (`Workspace.flashcard_count`, `Deck.card_count`)
avoid COUNT(*) fan-out. **All flashcard `now`-comparisons use naive-UTC** to match SQLite's
tz-stripped reads (a real bug found and fixed in testing). Bulk insert batches generated cards.

---

## 5. Backend Architecture

Layered like every domain (`backend/app/flashcards/`):

- **`models.py`** — the 4 tables above.
- **`scheduler.py`** — the pure SM-2 SRS engine (see §8). No DB, no clock beyond an injected `now`.
- **`schemas.py`** — DTOs (deck/card/review/analytics) + list enums.
- **`validation.py`** — pure deck/card/rating/scope/count validation.
- **`errors.py`** — transport-agnostic errors carrying `status_code`.
- **`repository.py`** — the ONLY SQL. Owner+workspace scoped, soft-delete aware; batched citations;
  and the aggregation queries: **review queue** (due-then-new), **deck stats**, **learning
  analytics** (accuracy, retention, streak, daily activity).
- **`engine.py`** — `PipelineFlashcardEngine`: the ONLY AI bridge. Plans retrieval queries →
  retrieval→context→LLM per query → parses structured cards → attaches citations. Lazy heavy imports.
- **`service.py`** — decks, cards, the generation pipeline (`generate_now`), SRS review
  (`submit_review`), conversions, and analytics. Business logic lives here.
- **`runner.py`** — `FlashcardRunner` (ThreadPool prod, own session **with workspace-counter
  maintenance**) + `InlineRunner` (tests) + `DeferredRunner`.
- **`api.py`** — one router under `/workspaces/{id}` exposing decks, cards, review, analytics.

**Generation pipeline** (`generate_now`): reload by trusted id → `clear_ai_cards` → `processing` →
consume engine events (`plan`/`card`/`final`), **bulk-inserting cards every 5** for progress +
partial results → `recount_deck` → bump `flashcard_count` → `completed`. Failure → `failed` with the
error, partial cards retained.

**Review engine** (`submit_review`): load card (must be active) → build `SRSState` → `scheduler.schedule(state, rating)`
→ persist the new SRS state onto the card → append an immutable `FlashcardReview` row.

**Error handling:** typed domain errors → `HTTPException` via `_handle`; workspace verified before any work.

---

## 6. Frontend Architecture

`frontend/leximind-frontend/src/`:

- **`api/flashcards.ts`** — full client (deck/card CRUD, generate, conversions, review queue +
  submit, analytics, export, `pollDeckStatus`).
- **`pages/FlashcardsDashboard.tsx`** — analytics panel (streak/due/accuracy/retention + 30-day
  activity chart) + "Study all due" CTA + deck grid + `GenerateDeckModal`. Honors "make flashcards
  from this" hand-offs.
- **`pages/DeckView.tsx`** — deck detail: stats, card list with per-card actions (edit, suspend,
  reset, favorite, delete), add card, regenerate; polls live during generation.
- **`pages/ReviewSession.tsx`** — the active-recall screen: 3D flip card, keyboard shortcuts
  (Space=flip, 1–4=grade, H=hint), four SM-2 buttons showing each scheduled interval, session
  progress + accuracy, response-time tracking, citation panel, favorite/suspend.
- **`components/flashcards/`** — `DeckCard`, `GenerateDeckModal`, `CardFormModal`, `AnalyticsPanel`,
  `constants.ts`.

### State management & routing
No global store (consistent with the app): each page owns its state with `useState`/`useRef`,
AbortController-guarded fetches. Routes under the workspace nesting:
`/flashcards`, `/flashcards/deck/:deckId`, `/flashcards/review?deck=<id?>`.

### Progress/statistics
The dashboard's `AnalyticsPanel` renders stat tiles + a dependency-free CSS bar chart (reviews vs
correct per day). The deck view shows per-deck stats; the review screen shows live session stats.

---

## 7. AI Integration

Flashcard generation reuses the production stack — **no duplicate AI pipeline**:

```
PipelineFlashcardEngine.generate(deck, db, count):
  queries = plan(deck.scope, subject, real doc headings)   # subject seed focuses a selection
  for query in queries (until `count` cards):
     result = pipeline.run(query, embed_fn=generate_embedding, filters=build_filter({workspace, doc, exclude_hidden}))
     ctx    = context_builder.build(query, result.chunks, query_keywords=result.analysis.keywords)
     raw    = complete(build_flashcard_prompt(card_type_pref, per_query, ctx.context))
     cards  = parse_flashcards(raw)                         # strict block format → dicts
     cits   = structured_citations(ctx.evidence)            # preserved provenance
     yield card(front, back, hint, type, citations=cits)    # dedup by front across queries
```

This threads through **Query Analysis → Hybrid Retrieval → RRF → Reranker → Duplicate Detection →
Evidence Ranking → Compression → Context Assembly** (Phases 1–2). `build_flashcard_prompt`
(`services/answer_service.py`) enforces the active-recall quality bar (one concept/card, no
ambiguity, concise, a hint, no paragraph-splitting) and a **strict block format**
(`Q:/A:/H:/T:` + `---`) that `parse_flashcards` decodes defensively. Citations are persisted as
`FlashcardCitation` rows — clicking one resolves the vector id (Module 3) and opens the PDF at the
page.

---

## 8. Spaced Repetition Design

Implemented in `backend/app/flashcards/scheduler.py` as a pure function.

**Algorithm: SM-2 variant.** SuperMemo-2 is the proven algorithm behind Anki. Each card carries an
**ease factor** (EF, how easy it is *for this user*) and an **interval** (days to next review). A
success multiplies the interval by EF → exponentially fewer reviews for known cards. We layer
Anki-style **four-button grading** and **learning/relearning steps** on top for a smoother early
experience (an "improved variant" rather than raw SM-2).

**Rating → quality mapping** (q ∈ 0..5; q < 3 = lapse): `again→2, hard→3, good→4, easy→5`.

**Review states** (`learning_stage`): `new → (good/easy) → review`; `review → (again) → relearning
→ (good) → review`.

**Interval calculation** (whole days — timezone-robust, matches a daily study habit):
- **Again** (lapse): interval → 1, repetitions → 0, `lapse_count++`, EF −0.20 (floor 1.3), stage → relearning.
- **Graduating** (new/learning/relearning + success): good → 1 then 6; hard → 1; easy → 4.
- **Review-stage success**: good → `round(interval × EF)`; hard → `round(interval × 1.2)`;
  easy → `round(interval × EF × 1.3)`; always moves forward (`≥ interval+1`).

**Ease factor**: textbook SM-2 update `EF += 0.1 − (5−q)(0.08 + (5−q)0.02)`, then −0.15 (hard) /
+0.15 (easy), clamped to **≥ 1.3**.

**Mastery score** (0..1, for analytics): `0.5·interval-maturity + 0.2·ease + 0.3·accuracy` — a card
only nears 1.0 when it is both well-spaced *and* reliably recalled. A card ≥ 0.8 is "mastered".

**Why this algorithm:** SM-2 is battle-tested, cheap to compute, easy to reason about and audit
(every review snapshots its schedule), and needs only per-card state — no ML training, no server
cron. It satisfies the brief's "proven algorithm (SM-2 or improved variant)" while the four-button
UX matches what learners already know from Anki.

---

## 9. API Documentation

All routes authenticated + workspace-scoped under `/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/decks` | Create empty deck | 201 `DeckOut` | 422 |
| POST | `/decks/generate` | **AI-generate deck** (async) | 202 `DeckOut` (queued) | 422 scope/count |
| POST | `/decks/from-note/{id}` · `/from-summary/{id}` · `/from-chat/{id}` | Generate from a source | 202 `DeckOut` | 404 source |
| GET | `/decks` | List decks (+ per-deck stats) | 200 `DeckListResponse` | |
| GET | `/decks/{id}` | Deck + stats | 200 `DeckWithStats` | 404 |
| GET | `/decks/{id}/status` | Poll generation | 200 `DeckOut` | 404 |
| PATCH | `/decks/{id}` | Rename/recolor/archive | 200 `DeckOut` | 404 |
| POST | `/decks/{id}/regenerate?count=` | Re-run AI (clears AI cards) | 200 `DeckOut` | 409 non-AI |
| POST | `/decks/{id}/cancel` | Cancel generation | 200 `DeckOut` | 409 terminal |
| DELETE | `/decks/{id}?permanent=` | Soft/hard delete (+cards) | 204 | 404 |
| GET | `/decks/{id}/export?format=csv\|md` | Download deck | 200 file | 404 |
| POST | `/decks/{id}/import` | Import delimited cards (`front\|back\|hint`) | 200 `DeckOut` | 404 |
| GET | `/decks/{id}/stats` | Deck learning stats | 200 `DeckStats` | 404 |
| POST | `/flashcards` | Create manual card (+citations) | 201 `FlashcardDetail` | 422 |
| GET | `/flashcards` | List cards (deck/type/status/favorite/sort) | 200 `FlashcardListResponse` | |
| GET | `/flashcards/{id}` | Card + citations | 200 `FlashcardDetail` | 404 |
| PATCH | `/flashcards/{id}` | Edit / move / favorite | 200 `FlashcardOut` | 404/422 |
| POST | `/flashcards/{id}/suspend` · `/unsuspend` · `/reset` | SRS state controls | 200 `FlashcardOut` | 404 |
| DELETE | `/flashcards/{id}` | Soft delete | 204 | 404 |
| GET | `/review?deck=&limit=&new_limit=` | **SRS queue** (due+new, with button intervals) | 200 `ReviewQueue` | |
| POST | `/flashcards/{id}/review` | **Submit a review** (rating + response time) | 200 `ReviewResult` | 409 suspended, 422 rating |
| GET | `/analytics?days=` | Workspace learning analytics | 200 `LearningAnalytics` | |

**Example — review:** `GET /review?deck=deck_x` → `{total_due, new_count, cards:[{card, buttons:[{rating, interval_days, label}]}]}`;
then `POST /flashcards/{id}/review {"rating":"good","response_time_ms":1200}` →
`{scheduled_interval:1, next_review_at, mastery_score}`.

---

## 10. Performance Optimizations

- **Scheduling** is O(1) pure arithmetic; no queries. `next_review_at` is a single indexed column →
  the review queue is one range scan (`ix_flashcards_ws_due`).
- **Bulk generation:** cards flushed in batches of 5 (progress visibility + fewer commits);
  `bulk_add_cards` inserts a batch + citations in one commit.
- **Analytics** computed in a bounded pass over the workspace's cards + reviews; denormalized
  counters (`flashcard_count`, `card_count`) avoid COUNT(*) fan-out on the dashboard.
- **Deck stats** are computed per-deck and returned batched with the deck list (no N+1).
- **No unnecessary recalculation:** `mastery_score`/`interval` are stored, not derived on read;
  `recount_deck` runs only on add/move/delete/generate.
- **Database indexing:** `ix_flashcards_ws_due`, `ix_flashcards_deck_status`, `ix_reviews_ws_date`,
  `ix_reviews_card_date`, `ix_decks_ws_updated`.
- **Frontend:** the review screen renders one card at a time; the activity chart is CSS-only (no
  chart library); deck generation streams in via polling.

---

## 11. Testing

**Unit tests**
- `test_flashcard_scheduler.py` (11) — the SM-2 core: new→graduate, easy skip, interval grows by
  ease, again = lapse + reset, EF floor 1.3, hard<good<easy ordering, mastery monotonicity,
  `next_review_at` matches interval, button previews, invalid rating.
- `test_flashcard_validation.py` (7) — deck name, card type/pref (reserved types rejected), scope
  inference/rules, count bounds, card content (cloze may omit back), rating, color/difficulty.
- `test_flashcard_service.py` (11) — deck + default deck, manual card + citations, bulk generation,
  review queue ordering, `submit_review` (schedule + log + analytics), again→lapse, suspend blocks
  review, reset, regenerate guard, deck stats, analytics streak/accuracy.

**Integration tests** (`test_flashcard_api.py`, 13) — the full learning loop over HTTP with the
inline runner + fake engine:

```
Workspace → Generate deck → Retrieval → Context → LLM (faked) → Citation validation → Persist cards
          → Review queue → Submit SM-2 reviews → Statistics update
```

Covers auth/scoping, deck CRUD + stats, async generation (queued→completed, cards+citations,
`flashcard_count` bump), validation 422s, card CRUD + suspend/reset, review queue (button intervals)
+ submit + queue-shrink, invalid rating, analytics (accuracy/streak/daily activity), CSV+MD export,
text import, note→deck conversion + regenerate + cancel-conflict.

**Results:** 42 new tests pass. Full suite: **293 passed** (only `test_reranker`/`test_eval` skipped
— they need torch/sentence-transformers, a pre-existing environment constraint). **No regressions**
in Phase 1/2 or Modules 1–6. Frontend `tsc -b` + `vite build` green; zero lint errors in new files.

---

## 12. File Changes Summary

### New backend files
- `app/flashcards/__init__.py` — package doc.
- `app/flashcards/models.py` — Deck/Flashcard/FlashcardCitation/FlashcardReview.
- `app/flashcards/scheduler.py` — **pure SM-2 SRS engine**.
- `app/flashcards/schemas.py` — DTOs + enums.
- `app/flashcards/validation.py` — pure validation.
- `app/flashcards/errors.py` — domain errors.
- `app/flashcards/repository.py` — all SQL + stats/queue/analytics aggregation.
- `app/flashcards/engine.py` — `PipelineFlashcardEngine` (AI bridge + card parsing).
- `app/flashcards/service.py` — decks/cards/generation/review/analytics.
- `app/flashcards/runner.py` — background/inline/deferred runners.
- `app/flashcards/api.py` — the flashcards router.
- `tests/test_flashcard_{scheduler,validation,service,api}.py` — 42 tests.

### New frontend files
- `src/api/flashcards.ts`, `src/pages/{FlashcardsDashboard,DeckView,ReviewSession}.tsx`,
  `src/components/flashcards/{DeckCard,GenerateDeckModal,CardFormModal,AnalyticsPanel,constants}.tsx/.ts`,
  `src/styles/flashcards.css`.

### Modified files (why)
- `app/db/base.py` — register flashcard models in `init_db()`.
- `app/main.py` — mount `flashcards_router`.
- `app/services/answer_service.py` — add `build_flashcard_prompt` + `parse_flashcards` (no new AI stack).
- `tests/conftest.py` — import flashcard models, add `FakeFlashcardEngine`, override the flashcards
  runner (inline).
- `src/App.tsx` — add the three flashcards routes.
- `src/types.ts` — add the Flashcards/Deck/Review/Analytics contracts.
- `src/main.tsx` — import `styles/flashcards.css`.
- `src/pages/WorkspaceDetail.tsx` — add the "🎴 Flashcards" entry point.
- `src/pages/NoteEditorPage.tsx` — "🎴 Flashcards" → generate from note.
- `src/components/summary/SummaryViewer.tsx` — "🎴 Flashcards" → generate from summary.
- `src/pages/ChatWorkspace.tsx` + `src/components/chat/ChatMessage.tsx` — "🎴 Flashcards" → generate from conversation.
- `src/pages/PdfViewer.tsx` + `src/components/viewer/actions.ts` — the "Flashcard" selection actions
  are now **live**: generate a selection-focused deck.

---

## 13. Future Compatibility

- **AI Tutor** — the SRS schedule + mastery scores tell a tutor exactly what a user is struggling
  with; the review log is the behavioral signal. Cards are grounded, so a tutor can explain from the
  source.
- **Knowledge Graph** — cards carry `document_id`/`note_id`/`summary_id`/`conversation_id` +
  citation `chunk_id`s: node/edge material linking cards ↔ sources ↔ concepts.
- **Adaptive learning** — `scheduler.py` is a pure, swappable function; FSRS or an ML-tuned
  scheduler can replace it behind the same `schedule(state, rating)` contract with zero call-site
  changes. Per-card ease already personalizes difficulty.
- **Exam mode** — a non-SRS "test everything now" pass is just a different queue query over the same
  cards + the same review log.
- **Gamification** — streak, accuracy, mastery, and daily activity are already computed; XP/badges
  sit on top of the analytics.
- **Collaborative learning** — `Deck.is_public`/`owner_id` are present for shared decks; the review
  log is per-user, so a shared deck can carry per-learner schedules.
- **Multimodal flashcards** — `Flashcard.media (JSON)` and reserved card types
  (`multiple_choice`/`image`/`diagram`) are schema-ready; only rendering + generation prompts are needed.

---

## 14. Lessons Learned

**Architecture decisions**
- *The scheduler is a pure function.* Keeping SM-2 free of DB/clock made it exhaustively testable
  (11 focused tests), auditable (every review snapshots its schedule), and swappable (FSRS later).
  This was the single most important design choice.
- *SRS state lives on the card.* Storing `next_review_at`/`ease_factor`/… as indexed columns turns
  "what's due?" into one range scan instead of a per-card computation — the whole review UX hinges
  on this.
- *One generation path.* Document/note/summary/chat/selection all resolve to a document-or-workspace
  retrieval scope + back-links, then flow through the same engine — five "sources" but one grounded,
  cited pipeline.
- *Reuse the module template.* Cloning the notes/summaries engine/runner/service split (with the
  event protocol + inline test runner) meant the async generation, cancellation, and test harness
  were correct immediately.

**Tradeoffs**
- *Day-granularity intervals.* No intraday learning steps (e.g. "10 min") — simpler, timezone-robust,
  and matches a daily study habit, at the cost of Anki's sub-day new-card drilling.
- *LLM card parsing.* A strict block format + a defensive parser is pragmatic and dependency-free,
  but depends on the model following the format; malformed blocks are dropped rather than repaired.
- *Naive-UTC datetimes.* Chosen to match SQLite's tz-stripped reads (a real bug surfaced in testing).
  A Postgres migration should standardize on tz-aware storage.

**Known limitations**
- No FSRS/ML scheduling yet (SM-2 only); no intraday steps; no per-card review-history UI; card
  generation quality is bounded by the LLM and the strict format.
- Analytics recompute per request (bounded pass) rather than incrementally — fine at current scale,
  a materialized daily rollup is the obvious optimization.

**Future improvements**
- FSRS scheduler behind the same contract; incremental analytics rollups; per-card history +
  interval graph; streaming generation; multimodal cards; shared/collaborative decks; an exam mode.

---

### Success criteria — status

✅ Codebase audited · ✅ Flashcard domain implemented · ✅ AI flashcard generation · ✅ Deck management ·
✅ Spaced-repetition engine (SM-2 variant) · ✅ Learning analytics · ✅ Citation preservation ·
✅ Professional review interface (flip/keyboard/difficulty/timer/citations) · ✅ Performance optimized ·
✅ Tests passing (42 new, 293 total) · ✅ No regressions in Phase 1/2 + Modules 1–6 · ✅ Documentation
complete (this file).
