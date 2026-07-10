# LexiMind — Phase 3 · Module 4: Persistent AI Chat Workspace

> **Status:** ✅ Complete · **New backend tests:** 35/35 passing (181 in the light env, incl. the
> shared Phase-1/2 + Module-1/2/3 suites) · **Frontend:** builds clean (`tsc -b && vite build`) ·
> **Builds on:** [phase1.md](./phase1.md), [phase2.md](./phase2.md),
> [phase3_module1.md](./phase3_module1.md), [phase3_module2.md](./phase3_module2.md),
> [phase3_module3.md](./phase3_module3.md)
>
> The canonical reference for Phase 3, Module 4 — a new engineer should understand the entire
> persistent-chat system (domain, message pipeline, streaming, memory, citation integration, and
> frontend) from this file alone.
>
> **One-line goal:** turn LexiMind from a stateless document-QA endpoint into a **research
> assistant with long-lived, workspace-scoped conversations** that pass every turn through the
> existing Retrieval + Context pipeline and stay grounded in the user's knowledge base.

---

## Table of Contents
1. [Module Overview](#1-module-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Database Design](#4-database-design)
5. [Backend Architecture](#5-backend-architecture)
6. [Frontend Architecture](#6-frontend-architecture)
7. [AI Pipeline Integration](#7-ai-pipeline-integration)
8. [Memory Strategy](#8-memory-strategy)
9. [API Documentation](#9-api-documentation)
10. [Performance Optimizations](#10-performance-optimizations)
11. [Testing](#11-testing)
12. [File Changes Summary](#12-file-changes-summary)
13. [Future Compatibility](#13-future-compatibility)
14. [Lessons Learned](#14-lessons-learned)

---

## 1. Module Overview

### Why persistent conversations are essential
Until now, `/query` was **stateless**: each question was answered in isolation, then forgotten.
That is a search box, not an assistant. Real research is a *thread* — you ask, read the source,
follow up ("and how does that compare to…"), refine, and return days later expecting the
assistant to remember. Persistent conversations turn LexiMind's strong retrieval into a genuine
**AI research assistant**: every chat belongs to a workspace, remembers its own history, keeps
its citations, and can be renamed, pinned, searched, and resumed.

### How this differs from stateless chat
| Stateless `/query` (before) | Persistent chat (this module) |
|---|---|
| One question → one answer, discarded | Durable `Conversation` of ordered `Message`s |
| No memory of prior turns | Token-aware conversation memory feeds the LLM |
| No organization | Create / rename / pin / archive / duplicate / search |
| Citations were transient response fields | Citations **persisted per message**, clickable into the viewer |
| Not resumable | Resume any conversation exactly where it left off |
| Blocking answer | **Streaming** token-by-token with cancellation |

Crucially, chat **never reimplements retrieval** — every turn flows through the same Phase-1
retrieval and Phase-2 context engine that power `/query`, so answers stay grounded and cited.

---

## 2. Previous Architecture

LexiMind had **no conversation concept**. The `Workspace` row carried a `chat_count` counter
(reserved in Module 1) but nothing incremented it, and there was no table for chats or messages.

```
Ask (Module-3 AI panel / AskQuestion)  →  POST /query {question, workspace_id}
   →  retrieval → context → LLM  →  answer + sources + citations  →  rendered once, then gone
```

| Concern | Before Module 4 |
|---|---|
| Conversation entity | none — no `conversations`/`messages` tables |
| Memory | none — each `/query` was independent |
| Organization | none — no list, rename, pin, archive, search of chats |
| Citation persistence | none — citations lived only in the transient response |
| Streaming | none — `generate_answer` blocked until the full answer returned |
| Resumability | none — reloading lost everything |

### Limitations
1. **No continuity** — the assistant couldn't reference what you just discussed.
2. **No history** — nothing to return to; no audit of past answers/sources.
3. **No organization** — power users accumulate dozens of threads; there was nowhere to put them.
4. **Blocking UX** — long answers appeared all-at-once after a wait, with no way to cancel.

> **The latent seam:** `Workspace.chat_count` and the whole `/query` pipeline already existed.
> Module 4 adds the conversation substrate and *wraps* that pipeline — it does not fork it.

---

## 3. New Architecture

```
Workspace (Module 1)
   └── Conversation (NEW — workspace + owner scoped, long-lived)
         └── Message[] (user / assistant, ordered)               ← persistent history
               ├── MessageCitation[] (document_id, page, text, confidence)  ← grounded provenance
               └── every USER turn triggers:
                     ↓
              Conversation memory (token-aware recent turns)
                     ↓
              Retrieval Engine   (Phase 1 — workspace-scoped, archived excluded)
                     ↓
              Context Engine     (Phase 2 — dedup→rank→budget→compress→assemble, citations kept)
                     ↓
              LLM (Ollama, STREAMED token-by-token)
                     ↓
              Assistant Message + Citations  →  persisted  →  streamed to the UI (SSE)
```

### One pipeline, injected — never duplicated
The chat module contains **no retrieval or context code**. A single injected `ChatEngine`
orchestrates the existing singletons (`RetrievalPipeline`, `ContextBuilderService`,
`answer_service`). The production engine (`PipelineChatEngine`) imports those heavy singletons
**lazily**, so `app.chat.*` imports with no faiss/torch and the whole conversation pipeline is
unit-testable against a fast fake engine (the exact pattern Modules 2–3 used for the vector store).

### Two transports, one code path
The message pipeline is a **single generator** (`ChatService.run_message`) yielding
`user → token* → done` (or `error`) events. The non-streaming JSON endpoint and the streaming SSE
endpoint both consume that same generator — so streaming and non-streaming can never diverge.

---

## 4. Database Design

Three **new tables** (created by `create_all`; no migration needed, consistent with Modules 2–3).

### Table: `conversations`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `conv_<uuid16>` |
| `workspace_id` | `String(40)` **INDEX** | scope; retrieval always uses this |
| `owner_id` | `String(40)` **INDEX** | owner scoping |
| `title` | `String(300)` | auto-generated from the first message, editable |
| `description` | `Text` | default `""` |
| `is_pinned` / `is_archived` | `Boolean` **INDEX** | organization + view splits |
| `deleted_at` | `DateTime` NULL | soft-delete tombstone |
| `message_count` | `Integer` | denormalized |
| `last_message_at` | `DateTime` NULL | default sort key |
| `document_scope` | `JSON` NULL | optional list of document ids to restrict retrieval |
| `temperature` | `Float` | multi-model future-proofing |
| `model_name` | `String(120)` | multi-model future-proofing |
| `system_prompt_version` | `String(40)` | prompt-versioning |
| `branched_from_message_id` | `String(40)` NULL | **branching** future-proofing (unused) |
| `created_at` / `updated_at` | `DateTime` | `updated_at` `onupdate` |

### Table: `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `msg_<uuid16>` |
| `conversation_id` | `String(40)` **INDEX** | parent |
| `role` | `String(20)` | `user` / `assistant` / `system` |
| `content` | `Text` | |
| `token_usage`, `latency_ms`, `retrieval_ms`, `context_size`, `citation_count` | `Integer` | per-turn telemetry |
| `metadata` (attr `meta`) | `JSON` NULL | status (`ok`/`error`), model, future image/audio parts |
| `created_at` | `DateTime` | |

### Table: `message_citations`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `cit_<uuid16>` |
| `message_id` | `String(40)` **INDEX** | parent assistant message |
| `document_id` | `String(40)` NULL | **vector** id → resolvable to a Document (Module 3 `/by-vector`) |
| `chunk_id` | `String(80)` NULL | exact chunk |
| `page_number` | `Integer` NULL | for jump-to-page |
| `workspace_id` | `String(40)` **INDEX** | isolation |
| `citation_text` | `Text` | snippet to highlight |
| `confidence` | `Float` NULL | evidence score (0–1-ish) |

### Indexes & why
| Index | Purpose |
|---|---|
| `ix_conversations_owner_ws` (`owner_id`,`workspace_id`) | every list query |
| `ix_conversations_ws_last` (`workspace_id`,`last_message_at`) | default recency sort |
| `conversations.is_pinned` / `is_archived` | pinned-first ordering + view filters |
| `ix_messages_conv_created` (`conversation_id`,`created_at`) | history reads in order |
| `messages.conversation_id`, `message_citations.message_id` | parent lookups + batched citation loads |

### Relationships & scalability
Logical FKs (`conversation.workspace_id/owner_id`, `message.conversation_id`,
`citation.message_id`) — no hard DB constraints, consistent with the project's stance. Message +
citation reads are **batched** (list messages, then one `IN (...)` query for all their citations →
no N+1). Future-proofed for **multi-model** (`model_name`/`temperature`/`system_prompt_version`),
**branching** (`branched_from_message_id`), and **document-scoped** chats (`document_scope`) — all
present as columns, none activated yet.

---

## 5. Backend Architecture

Clean-architecture package `app/chat/` (same contract as the other domains — logic never in
handlers, SQL only in repositories, **no faiss import**, **no separate retrieval logic**):

```
models.py      Conversation / Message / MessageCitation ORM (3 new tables)
schemas.py     DTOs + list-query enums (sort/archived/pinned)
validation.py  pure title/description/message validation + auto-title
errors.py      transport-agnostic domain errors (404/409/422)
repository.py  ConversationRepository + MessageRepository (owner+ws scoped, batched citations)
memory.py      token-aware conversation-history selection (+ summarization placeholder)
engine.py      ChatEngine protocol + PipelineChatEngine (the ONLY bridge to the AI pipeline)
service.py     conversation lifecycle + run_message (the single stream/non-stream pipeline)
api.py         authenticated routes under /workspaces/{id}/conversations
```

### Repositories
`ConversationRepository` — owner+workspace scoped, soft-delete aware; `list` in two queries
(count + windowed select) with **pinned-first** ordering, search (title/description), archived +
pinned filters, sort, pagination; `search` is the broad "find that chat" query (title OR
description OR message content OR citation text, via `IN` subqueries). `MessageRepository` — add,
paginated `list`, `recent` (for memory), **batched** `citations_for`, and a
`delete_for_conversation` purge.

### Services
`ChatService` owns conversation CRUD (create/update/pin/archive/restore/**duplicate**/delete),
workspace `chat_count` maintenance (best-effort), and the **message pipeline** `run_message`.
`run_message` persists the user turn, auto-titles on the first message, builds token-aware memory
from prior turns, delegates the answer to the injected engine, then persists the assistant turn +
citations and updates counters — all while **yielding events** so streaming and non-streaming
share one implementation.

### Streaming
The SSE endpoint wraps `run_message` in a `StreamingResponse` of `text/event-stream`, emitting
`event: user|token|done|error` frames. Token frames arrive as the LLM produces them
(`answer_service.stream_answer` uses `subprocess.Popen` over Ollama and yields decoded chunks).
**Cancellation** = the client aborts the request → the generator is closed → the subprocess is
terminated in a `finally`. The user turn is persisted *before* streaming, so an interruption never
corrupts history (the UI just reloads).

### Memory
`memory.select_history` picks the most recent prior turns that fit a **token budget**
(`chat_history_token_budget`, default 1500) and message cap (`chat_history_max_messages`, default
20), using the Phase-2 heuristic token counter — so the prompt (system + history + retrieved
context + answer) always fits the model window. A `summarize_older` seam is reserved for a future
summarization module.

### Search & validation & errors
Search: the `/search` endpoint (broad) + the list `search` param (cheap title/description).
Validation is pure (`validation.py`): title/description/message-content limits, control-char
rejection, and `title_from_message` auto-titling. Errors are transport-agnostic
(`ConversationNotFound` 404, `ConversationStateError` 409, `ChatValidationError` 422), mapped to
HTTP by a `_handle` translator — no business logic in the API.

---

## 6. Frontend Architecture

**Stack additions:** `react-markdown` + `remark-gfm` + `rehype-highlight` (Markdown, GFM tables,
code-block syntax highlighting). Everything else unchanged.

### Routing
| Route | Page | Purpose |
|---|---|---|
| `/workspace/:workspaceId/chat` | `ChatWorkspace` | chat home (sidebar + empty state) |
| `/workspace/:workspaceId/chat/:conversationId` | `ChatWorkspace` | an open conversation |

`WorkspaceDetail` gains a "💬 Open Chat" entry point. Everything is under `:workspaceId`, so
switching workspace switches the conversation list (workspace isolation by construction).

### Components & state
```
ChatWorkspace (page — reads :workspaceId/:conversationId)
├── ConversationSidebar   new-chat · debounced search (/search) · pinned + recent list · row menu
│                          (Rename · Pin/Unpin · Duplicate · Archive/Restore · Delete) · archived toggle
└── ChatWindow            header (title + inline rename, model/temp) · message list · composer
     ├── ChatMessage[]    memoized bubble; assistant = Markdown+code/tables; actions:
     │                    Copy · Regenerate (assistant) · Edit/Retry (user) · CitationCard[]
     ├── CitationCard      source · page · confidence → click → open the Module-3 viewer
     └── ChatComposer      auto-grow textarea, Enter=send/Shift+Enter=newline, Send↔Stop
hook:  useChat            messages, streaming state, send/cancel/regenerate, paginated history
api:   src/api/chat.ts    conversation/message clients + streamMessage() (fetch + SSE reader)
styles: src/styles/chat.css
```

State is page-local + the `useChat` hook (no Redux/Zustand — project convention). Streaming uses
`fetch` + `response.body.getReader()` (EventSource can't POST) with an `AbortController` for the
Stop button; a transient "typing" assistant bubble is filled by `token` events and finalized on
`done`. Long histories load lazily (paginated, infinite-scroll upward); bubbles are memoized;
search is debounced; superseded requests are aborted.

### Citation navigation (reuses Module 3)
A citation card carries the **vector** `document_id`. Clicking it resolves the real document via
`getDocumentByVector(ws, document_id)` (Module 3) and navigates to
`/workspace/:ws/document/:docId` with router `state.citation = { page, text }`. `PdfViewer` reads
that state on load and uses the existing `useCitationHighlight` hook to jump to the page and
highlight the passage — closing the loop from a chat answer straight to the source page.

---

## 7. AI Pipeline Integration

Every user message flows through the **existing** pipeline; the chat module adds only
orchestration + persistence:

```
User message (+ conversation memory)
        ↓
build filter { workspace_id, exclude archived/deleted docs, optional document_scope }
        ↓
RetrievalPipeline.run  →  query analysis · dense + BM25 · RRF · rerank      (Phase 1, unchanged)
        ↓
ContextBuilderService.build  →  dedup · evidence-rank · budget · compress · assemble  (Phase 2)
        ↓
answer_service.build_chat_prompt(system + memory + context + turn)
        ↓
answer_service.stream_answer  →  Ollama, streamed tokens
        ↓
structured_citations(evidence)  →  persisted MessageCitations  →  streamed to the UI
```

The chat engine reuses `pipeline`, `context_builder`, `generate_embedding`, `build_filter`,
`structured_citations`, and the Module-2 `DocumentRepository.list_excluded_vector_ids` (archived
exclusion). It adds exactly two small things to `answer_service`: `build_chat_prompt` (system +
memory + context + turn) and `stream_answer` (token streaming). **Duplicate detection, evidence
ranking, compression, context assembly, and citation preservation are all inherited unchanged** —
there is no second retrieval path.

---

## 8. Memory Strategy

- **Conversation history** — prior turns are the assistant's short-term memory. `run_message`
  fetches the recent turns *before* persisting the new user message, so memory reflects the
  conversation up to (not including) the current question.
- **Token budgeting** — `select_history` walks newest→oldest, accumulating estimated tokens
  (Phase-2 heuristic counter), and stops at `chat_history_token_budget` (1500) or
  `chat_history_max_messages` (20), returning turns in chronological order. This guarantees
  `system + history + retrieved context + answer` fits the model's context window.
- **Context selection** — retrieval is grounded in the *current* message (documents), while
  history provides *conversational* continuity in the prompt. The two are complementary and kept
  separate, so a follow-up like "explain that more simply" still retrieves the right passages.
- **Future summarization** — when a conversation outgrows the budget, older turns will be folded
  into a running summary rather than dropped. The `memory.summarize_older` seam is the hook;
  today behavior is a clean sliding window over recent turns.

---

## 9. API Documentation

All routes under `/workspaces/{workspace_id}/conversations`, require `Authorization: Bearer
<token>`, and 404 if the workspace isn't owned.

### Conversation CRUD
- `POST ""` → 201 `ConversationOut`. Body `{ title?, description?, document_scope?, temperature?,
  model_name? }`. Bumps `Workspace.chat_count`.
- `GET ""` → `{ items, total, page, page_size, pages }`. Query: `page, page_size, search,
  archived(active|archived|all), pinned(any|pinned), sort_by(last_message_at|created_at|updated_at|title),
  order(asc|desc)`. **Pinned conversations always sort first.**
- `GET "/search?q=&limit="` → `ConversationOut[]` — broad search (title, description, message
  content, citation text).
- `GET "/{id}"` → `ConversationOut`. `PATCH "/{id}"` (partial) → `ConversationOut`.
- `POST "/{id}/pin" | "/unpin" | "/archive" | "/restore"` → `ConversationOut`
  (409 on illegal archive/restore transition).
- `POST "/{id}/duplicate"` → 201 `ConversationOut` (copies message + citation history).
- `DELETE "/{id}?permanent="` → 204 (soft by default; permanent purges messages + citations).

### Messages
- `GET "/{id}/messages?page=&page_size="` → `{ items: MessageOut[], total, page, page_size, pages }`
  (oldest→newest; each message carries its `citations`).
- `POST "/{id}/messages"` (non-streaming) → `{ ok, conversation_id, user: MessageOut,
  assistant: MessageOut }`. Body `{ content, top_k? }`.
- `POST "/{id}/messages/stream"` (streaming) → `text/event-stream`.

### Streaming protocol (SSE)
Each frame is `event: <type>\ndata: <json>\n\n`:
```
event: user   data: <MessageOut>            # persisted user turn
event: token  data: {"text": "…"}           # 0+ progressive assistant tokens
event: done   data: <MessageOut>            # persisted assistant turn (with citations)
event: error  data: {"error": "…"}          # failure; user turn is already persisted
```
The client parses frames incrementally from `fetch().body.getReader()`; **cancellation** is an
`AbortController` abort (the server terminates the LLM subprocess).

### Validation & errors
`422` invalid title/description/empty message · `404` unknown conversation/workspace · `409`
illegal archive/restore · `401` unauthenticated.

### DTOs
`ConversationOut { id, workspace_id, owner_id, title, description, is_pinned, is_archived,
message_count, last_message_at, document_scope, temperature, model_name, system_prompt_version,
created_at, updated_at }`. `MessageOut { id, conversation_id, role, content, token_usage,
latency_ms, retrieval_ms, context_size, citation_count, meta, created_at, citations: CitationOut[] }`.
`CitationOut { id, document_id, chunk_id, page_number, workspace_id, citation_text, confidence }`.

---

## 10. Performance Optimizations

- **Streaming** — tokens surface as generated (SSE), so time-to-first-token is tiny and long
  answers never block; **Stop** aborts instantly.
- **No duplicate retrieval** — one pipeline run per turn; the chat module never re-queries.
- **Batched citation loads** — message history loads citations for the whole page in a single
  `IN (...)` query (no N+1).
- **Two-query listing** — conversation lists are count + windowed select with pinned-first,
  indexed ordering; message history is paginated with an indexed `(conversation_id, created_at)`.
- **Token-bounded memory** — history is capped by token budget + message count, so prompt size
  (and LLM latency/cost) stays bounded regardless of conversation length.
- **Frontend** — lazy conversation list + paginated/infinite-scroll history, memoized message
  bubbles, debounced search, `AbortController` on superseded/streamed requests, and the chat page
  ships as its own lazy route chunk.
- **Denormalized counters** — `message_count`/`last_message_at` on the conversation give O(1)
  sidebar rendering.

---

## 11. Testing

**35 new backend tests**, all passing, on the light harness (in-memory SQLite + minimal app; the
chat router mounts with a deterministic **`FakeChatEngine`** overriding the real AI engine, so the
whole conversation pipeline — persistence, streaming, citations, memory — is exercised without
faiss/LLM).

| File | Type | Covers |
|---|---|---|
| `test_chat_validation.py` | unit | title default/normalize/length/control, description cap, message required/cap, auto-title (5) |
| `test_chat_memory.py` | unit | recency + message cap, **token-budget cutoff**, skip-empty + order, render, empty (5) |
| `test_chat_repository.py` | unit | owner scoping, soft-delete hide, filters + **pinned-first**, list search, **broad search across messages + citations**, message order/recent/batched citations, purge (7) |
| `test_chat_service.py` | unit | create counter bump, pin/archive/restore state machine, soft/hard delete decrement, **run_message persists turn + citations + auto-title**, **memory threads prior turns**, duplicate copies history, **engine-error persists error turn** (7) |
| `test_chat_api.py` | **integration** | auth 401, foreign-workspace 404, full lifecycle (create→rename→pin→archive→restore→delete), chat_count bump, **send message persists + cites + auto-titles**, **streaming SSE (user→token→done, tokens concatenate, citations)**, duplicate + broad search, **workspace isolation** (8) |
| `test_citations.py` | unit | `structured_citations` incl. the new `confidence` field (3) |

### The required integration flow
`test_stream_message_sse` drives Workspace → Create Chat → Send (stream) → parses the SSE frames
(`user` → `token`* → `done`), asserts the streamed tokens concatenate to the answer and the
persisted assistant message carries its citations — the Module-4 spec's end-to-end path
(retrieval/context/LLM are the injected fake; the pipeline wiring is real).

### No regression
The only shared files touched are additive: `answer_service.py` (two new functions + a citation
field), `config.py` (two settings), `db/base.py`/`main.py`/`conftest.py` (register + mount a
router). **Full light suite: 181 passed** (was 149 for Module 3); the only non-runs are the same 4
faiss/`rank_bm25` environmental suites, untouched.

```bash
cd backend && python -m pytest tests/test_chat_*.py tests/test_citations.py -q     # 35 passed
cd backend && python -m pytest tests/ -q \
  --ignore=tests/test_bm25.py --ignore=tests/test_hybrid.py \
  --ignore=tests/test_integration.py --ignore=tests/test_query_analysis.py         # 181 passed
```

Frontend: `npm run build` (`tsc -b && vite build`) compiles clean with the markdown deps; the chat
page ships as its own lazy chunk.

---

## 12. File Changes Summary

### New files — Backend
| File | Purpose |
|---|---|
| `app/chat/__init__.py` | package contract/docstring |
| `app/chat/models.py` | `Conversation` / `Message` / `MessageCitation` ORM (3 new tables) |
| `app/chat/schemas.py` | DTOs + list-query enums |
| `app/chat/validation.py` | pure title/description/message validation + auto-title |
| `app/chat/errors.py` | transport-agnostic domain errors |
| `app/chat/repository.py` | conversation + message SQL (scoped, batched citations, broad search) |
| `app/chat/memory.py` | token-aware history selection + summarization placeholder |
| `app/chat/engine.py` | `ChatEngine` protocol + `PipelineChatEngine` (reuses the AI pipeline, lazy) |
| `app/chat/service.py` | conversation lifecycle + the single `run_message` pipeline |
| `app/chat/api.py` | authenticated routes incl. non-streaming + SSE streaming |
| `tests/test_chat_validation.py`, `test_chat_memory.py`, `test_chat_repository.py`, `test_chat_service.py`, `test_chat_api.py` | 32 new tests |

### Modified files — Backend
| File | Reason |
|---|---|
| `app/services/answer_service.py` | add `build_chat_prompt`, `stream_answer`, and a `confidence` field on `structured_citations` |
| `app/core/config.py` | add `chat_history_token_budget`, `chat_history_max_messages` |
| `app/db/base.py` | register `app.chat.models` in `init_db()` |
| `app/main.py` | mount the chat router |
| `tests/conftest.py` | register chat models, mount the chat router, add the `FakeChatEngine` override |
| `tests/test_citations.py` | assert the new `confidence` field |

### New files — Frontend
| File | Purpose |
|---|---|
| `src/api/chat.ts` | conversation/message client + `streamMessage` (fetch + SSE reader) |
| `src/pages/ChatWorkspace.tsx` | the chat page (sidebar + chat window), citation navigation |
| `src/components/chat/ConversationSidebar.tsx` | list/search/pin/archive + row menu + new-chat |
| `src/components/chat/ChatMessage.tsx` | memoized bubble (Markdown/code/tables) + actions + citation cards |
| `src/components/chat/ChatComposer.tsx` | auto-grow composer, Enter-to-send, Send↔Stop |
| `src/components/chat/CitationCard.tsx` | citation chip → open the viewer |
| `src/components/chat/useChat.ts` | messages/streaming/send/cancel/regenerate/history hook |
| `src/styles/chat.css` | sidebar, bubbles, markdown, citation cards, composer, typing indicator |

### Modified files — Frontend
| File | Reason |
|---|---|
| `src/types.ts` | add `Conversation`, `ChatMessage`, `ChatCitation`, list/params/SSE types |
| `src/App.tsx` | add lazy `/workspace/:workspaceId/chat[/:conversationId]` routes |
| `src/main.tsx` | import `styles/chat.css` |
| `src/pages/WorkspaceDetail.tsx` | "💬 Open Chat" entry point |
| `src/pages/PdfViewer.tsx` | honor an initial citation from router state (jump + highlight) |
| `package.json` | add `react-markdown`, `remark-gfm`, `rehype-highlight` |

---

## 13. Future Compatibility

| Future capability | What Module 4 already provides |
|---|---|
| **AI Summaries** | conversations + messages are the raw material; `document_scope` + the engine can summarize a thread or a document; `summarize_older` seam for memory |
| **Notes** | any assistant message + its citations can be saved as a note; `MessageCitation` already anchors to document/page/chunk |
| **Flashcards** | Q→A turns map naturally to card front/back with grounded citations |
| **Knowledge Graph** | persisted `MessageCitation` edges (conversation → message → document → page → chunk) are graph edges; `by-vector` resolves nodes |
| **Agents** | the injected `ChatEngine` interface is the extension point — a multi-step/tool-using agent implements the same `generate()` event contract with no changes to persistence/streaming/UI |
| **Multimodal conversations** | `Message.meta` (JSON) + `role` already accommodate image/audio parts; the stream contract is content-agnostic |
| **Collaboration** | `owner_id` is real; shared/branched conversations use the reserved `branched_from_message_id` + a future membership table (new table, no migration) |

Every future capability plugs into the **`ChatEngine` seam** (swap/extend the answer generator) or
reads the **persisted messages/citations** — the conversation substrate itself doesn't change.

---

## 14. Lessons Learned

### Architecture decisions
- **Wrap the pipeline, never fork it.** The chat engine is an injected orchestrator over the
  existing Phase-1/2 services + `answer_service`. There is exactly one retrieval path in the
  system, so grounding/citations are identical to `/query`.
- **One generator, two transports.** `run_message` yields `user → token* → done` events; the SSE
  and JSON endpoints both consume it. Streaming and non-streaming can't drift, and the pipeline is
  testable without a real LLM by substituting a fake engine that emits the same events.
- **Inject the heavy engine.** Like the vector store in Modules 2–3, the AI engine is a FastAPI
  dependency imported lazily — `app.chat.*` stays faiss-free and every conversation behavior is
  unit-tested in the light env.
- **Persist the user turn first.** Doing so before streaming means a cancel/error/disconnect never
  corrupts history — the UI just reloads the conversation.
- **New tables, not new columns.** Three additive tables avoid the no-Alembic migration gap.

### Tradeoffs
- **Sliding-window memory** (token-bounded recent turns) rather than summarization — simple,
  predictable, and cheap; the `summarize_older` seam upgrades it later without touching callers.
- **Ollama subprocess streaming** (`Popen`, chunked stdout) rather than the HTTP API — keeps the
  offline-first, dependency-light stance; swap to the streaming HTTP API behind `stream_answer`.
- **SSE over WebSockets** — one-directional streaming is all a turn needs; SSE is simpler,
  proxy-friendly, and cancels cleanly via request abort.
- **Broad search via `LIKE` subqueries** — no new search infra; a future FTS index backs the same
  endpoint if corpora grow.

### Known limitations
- No token-exact usage from the LLM yet (heuristic estimates fill `token_usage`/`context_size`);
  wire real counts when moving to the Ollama HTTP API.
- Reconnect mid-stream resumes by reloading history, not by replaying the in-flight token stream.
- Regenerate/edit create new turns rather than versioning a message (branching columns are
  reserved for a future editing/branching module).

### Future improvements
1. Conversation summarization (activate `summarize_older`) for very long threads.
2. Real token accounting + per-model settings via the Ollama HTTP API (`model_name`/`temperature`
   are already stored per conversation).
3. Message branching/versioning using `branched_from_message_id`.
4. Server-push reconnect that replays the tail of an in-flight stream.
5. Shared/collaborative conversations (membership table + `owner_id` already real).
```
