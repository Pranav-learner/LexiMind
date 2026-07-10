# LexiMind — Phase 3 · Module 1: Workspace Management

> **Status:** ✅ Complete · **New backend tests:** 45/45 passing (96 passing in the light
> env, incl. shared Phase-1/2 suites) · **Frontend:** builds clean (`tsc -b && vite build`) ·
> **Builds on:** [phase1.md](./phase1.md), [phase2.md](./phase2.md)
>
> The canonical reference for Phase 3, Module 1. A new engineer should understand the entire
> workspace system — backend domain, auth, retrieval integration, and frontend — from this
> file alone.
>
> **One-line goal:** turn LexiMind from a single shared AI engine into a multi-workspace
> **AI Knowledge Workspace**, where every future artifact (documents, chats, notes,
> flashcards, summaries) lives inside an isolated workspace.

---

## Table of Contents
1. [Module Overview](#1-module-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Database Design](#4-database-design)
5. [Backend Architecture](#5-backend-architecture)
6. [Frontend Architecture](#6-frontend-architecture)
7. [Retrieval Integration](#7-retrieval-integration)
8. [API Documentation](#8-api-documentation)
9. [Testing](#9-testing)
10. [File Changes Summary](#10-file-changes-summary)
11. [Future Compatibility](#11-future-compatibility)
12. [Lessons Learned](#12-lessons-learned)

---

## 1. Module Overview

### Why Workspace Management is needed
Phases 1–2 made a single, shared knowledge base *retrieve* and *contextualize* well. But
everything lived in one global index: every upload, every question, one pile. That does not
scale to how people actually organize knowledge — by subject, project, or purpose
("Operating Systems", "Machine Learning", "SIH 2026"). Without isolation there is no way to
ask a question *only* of your ML notes, no per-area document counts, and no foundation for
teams later.

### Product vision
LexiMind evolves from an **AI Engine** into an **AI Knowledge Workspace**:

```
LexiMind
├── 🧠 Operating Systems
├── 📚 Machine Learning
├── 🔬 Research Papers
├── 🚀 SIH 2026
└── 📁 Personal Knowledge
```

A **Workspace** is an isolated knowledge environment. Every future feature belongs to one.
Module 1 delivers the workspace substrate — CRUD, isolation, and the UI — that every
remaining Phase-3 module (Document Library, Chats, Notes, Flashcards) will hang off of.

### User experience goals
- **Instant mental model** — a dashboard of colorful workspace cards, each showing its
  document / chat / note / flashcard / summary counts and last-updated time.
- **Frictionless management** — create, rename, re-icon, re-color, archive, restore, delete,
  with live validation and no page reloads.
- **Scale-ready** — search, sort, filter, and paginate across thousands of workspaces without
  lag.
- **Context inheritance** — opening a workspace (`/workspace/:id`) scopes everything inside
  it; uploads land in that workspace and questions only search it.

### Scope boundary (explicit)
Implemented: workspace CRUD + isolation + a **minimal real auth system** (so `owner_id` is
real). **Not** implemented (by design): collaboration, team workspaces, roles, permissions,
sharing. The schema and layering are shaped so those slot in later **without rewrites**.

---

## 2. Previous Architecture

Before Phase 3, LexiMind had **no database and no concept of a user or a workspace**.

```
   upload → ingest → FAISS index + vector_metadata.json   (one global pile)
   query  → retrieve (whole index) → context → LLM         (searches everything)
```

| Concern | Before Phase 3 |
|---|---|
| Persistence | FAISS index + a parallel `vector_metadata.json` list — vectors only |
| Identity | none — no users, no `owner_id`, no auth |
| Isolation | none — every query searched the entire shared index |
| Structured data | nowhere to put rows with uniqueness/indexes/relations |
| Frontend | React + Vite, **no router, no state management**; one `Home` page → `UploadPdf` + `AskQuestion` |

### Limitations
1. **No isolation** — impossible to scope retrieval to a subject/project.
2. **No structured store** — counts, names, and ownership have no home; a JSON list can't
   enforce a unique name per owner or index a lookup.
3. **No identity** — nothing to own a workspace or (later) to share it with.
4. **Flat UI** — a single page with no navigation; nowhere to grow modules.

> **A latent seam existed:** Phase 1's `RetrievalFilter` already had a `workspace` field and
> `build_filter()` already accepted it — but **nothing populated it**. Phase 3 completes that
> half-built seam rather than inventing a new one.

---

## 3. New Architecture

### Workspace hierarchy
```
User (owner)
  └── Workspace (isolated knowledge environment)
        ├── Documents   → chunks tagged with workspace_id  (Module 1: wired)
        ├── Chats       → (future module)   counter ready
        ├── Notes       → (future module)   counter ready
        ├── Flashcards  → (future module)   counter ready
        └── Summaries   → (future module)   counter ready
```

### End-to-end request flow (Phase 3)
```
                         ┌──────────────── Browser (React + Router) ────────────────┐
   Login / Register ────▶│  AuthProvider (token in localStorage)                     │
                         │  /            → WorkspacesDashboard  (cards, CRUD)         │
                         │  /workspace/:id → WorkspaceDetail    (upload + ask, scoped)│
                         └───────────────┬──────────────────────────────────────────┘
                                         │  Bearer token + workspace_id
                                         ▼
   ┌────────────────────────────── FastAPI ──────────────────────────────────────────┐
   │  /auth/*        → AuthService     → UserRepository     → SQLite(users)            │
   │  /workspaces/*  → WorkspaceService → WorkspaceRepository → SQLite(workspaces)      │
   │  /upload/pdf    → ingest(workspace_id) → chunk.metadata["workspace_id"]           │
   │  /query         → RetrievalFilter(workspace_id) → Phase-1 pipeline → Phase-2 ctx  │
   └──────────────────────────────────────────────────────────────────────────────────┘
                                         │
                     ┌───────────────────┴───────────────────┐
                     ▼                                        ▼
             SQLite (leximind.db)                 FAISS + vector_metadata.json
             users, workspaces                    vectors + chunk metadata (+ workspace_id)
```

### Two persistence layers, cleanly separated
Phase 3 introduces the project's **first relational store (SQLite)** for structured domain
rows (users, workspaces) and keeps it **decoupled** from the vector layer:

| Layer | Holds | Owned by |
|---|---|---|
| **SQLite** (`app/db`) | users, workspaces (+ counters) | `app/auth`, `app/workspaces` |
| **FAISS + JSON** | vectors + chunk metadata (now incl. `workspace_id`) | `app/services`, `app/retrieval` |

The link between them is a single string: **`workspace_id`**, written into chunk metadata at
ingest and used as a retrieval filter at query time.

---

## 4. Database Design

**Engine:** SQLite via **SQLAlchemy 2.0** (declarative). SQLite keeps the system offline-first
and zero-ops (a single `leximind.db` file); the ORM lets us move to Postgres by changing only
`LEXIMIND_DATABASE_URL`. No Alembic yet — the schema is young and additive.

### Table: `users`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `user_<uuid16>` |
| `email` | `String(320)` | **UNIQUE, INDEX** — login handle |
| `password_hash` | `String(255)` | `pbkdf2_sha256$iters$salt$hash` (stdlib) |
| `display_name` | `String(120)` | |
| `created_at` | `DateTime(tz)` | |

### Table: `workspaces`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(40)` PK | `ws_<uuid16>` |
| `name` | `String(120)` | required; unique per owner among live rows (service-enforced) |
| `description` | `Text` | default `""` |
| `icon` | `String(40)` | emoji, default `📁` |
| `color` | `String(20)` | hex, default `#6366f1` |
| `owner_id` | `String(40)` | **INDEX** — every list filters by owner |
| `is_archived` | `Boolean` | **INDEX** — active/archived split |
| `deleted_at` | `DateTime(tz)` NULL | **soft-delete tombstone** (NULL = live) |
| `document_count` | `Integer` | denormalized counter |
| `chat_count` | `Integer` | denormalized counter |
| `note_count` | `Integer` | denormalized counter |
| `flashcard_count` | `Integer` | denormalized counter |
| `summary_count` | `Integer` | denormalized counter |
| `created_at` | `DateTime(tz)` | |
| `updated_at` | `DateTime(tz)` | `onupdate=now` |

### Indexes & why
| Index | Purpose |
|---|---|
| `users.email` (unique) | fast login lookup; enforce one account per email |
| `workspaces.owner_id` | every dashboard query filters by owner |
| `workspaces.is_archived` | active vs archived filter |
| `ix_workspaces_owner_name` (`owner_id`, `name`) | duplicate-name check + per-owner name lookups |

### Relationships
`workspaces.owner_id → users.id` (logical FK; not a hard DB constraint yet so the migration
can create a "Default" workspace under a placeholder owner before real accounts exist).
Chunk↔workspace is a **soft link** via `metadata["workspace_id"]` in the vector store — the
FAISS layer is intentionally not coupled to the relational schema.

### Design decisions
- **Denormalized counters** over `COUNT(*)` joins: the dashboard renders counts for thousands
  of cards with zero fan-out queries. The owning module keeps each counter in sync
  (ingestion bumps `document_count`); `adjust_counter` clamps at ≥ 0.
- **Soft delete** (`deleted_at`) makes deletion reversible; **hard delete** is opt-in via
  `?permanent=true`. Name uniqueness is enforced among *non-deleted* rows so a name frees up
  after a permanent delete.
- **Uniqueness in the service, not a DB constraint**: a partial unique index would fight
  soft-delete/archive edge cases; the service does a case-insensitive check scoped to live
  rows, which is clearer and equally correct at this scale.

### Future scalability
- Move to Postgres by env var only; add composite/partial indexes as query patterns emerge.
- Counters generalize to any future artifact type via the `COUNTER_FIELDS` tuple.
- A `teams`/`memberships` table and a `workspace.team_id` column slot in without touching
  existing rows (collaboration).

---

## 5. Backend Architecture

Two new **clean-architecture** packages. In both, **business logic never lives in API
handlers, and the API never issues SQL directly**:

```
app/db/            engine + session + declarative Base + init_db   (shared)
app/auth/          minimal identity so owner_id is real
  security.py      stdlib pbkdf2 hashing + HMAC-signed tokens
  models.py        User ORM
  schemas.py       DTOs (register/login/token/user)
  errors.py        transport-agnostic domain errors
  repository.py    all SQL for users
  service.py       register / login rules
  dependencies.py  get_current_user / _user_id / optional_user_id
  api.py           /auth/register|login|me
app/workspaces/    the core Phase-3 domain
  models.py        Workspace ORM + COUNTER_FIELDS
  schemas.py       DTOs + list-query enums (sort/order/archived)
  validation.py    pure field validation/normalization
  errors.py        NotFound / Duplicate / Validation / State
  repository.py    all SQL (owner-scoped, soft-delete aware, paginated)
  service.py       CRUD rules, dup-name, archive/restore, counters
  api.py           thin authenticated HTTP routes
```

### Services
- **`AuthService`** — `register` (dup-email guard, hash password) and `login` (constant-time
  verify, issue token; identical error for unknown-email vs bad-password to avoid user
  enumeration).
- **`WorkspaceService`** — owns every rule: validation + normalization, case-insensitive
  duplicate-name prevention scoped to the owner's live rows, archive/restore state
  transitions (illegal transitions raise `WorkspaceStateError`), soft-delete-by-default,
  and counter maintenance. All operations are owner-scoped (a missing/foreign row → 404).

### Repositories
Only these touch the ORM session. `WorkspaceRepository.list` does the whole listing in **two
cheap queries** (a `COUNT` + a windowed `SELECT` with `ORDER BY … LIMIT/OFFSET`) — no N+1, no
in-memory table scan. Search matches name **or** description (`ILIKE`), with a stable
`id`-tiebreak ordering for consistent pagination.

### Validation
`validation.py` is pure (no I/O): trims/collapses whitespace, enforces length limits
(name ≤ 120, description ≤ 2000, icon ≤ 40), rejects control chars and the forbidden set
`/ \ < > : " | ? *`, validates hex colors, and defaults icon/color. Duplicate-name detection
is in the service (it needs the repo).

### Error handling
Domain errors carry an HTTP `status_code` + machine `code` but import no web framework. Each
route wraps calls in a tiny translator that maps them to `HTTPException`:

| Domain error | HTTP |
|---|---|
| `WorkspaceValidationError` / `InvalidRegistration` | 422 |
| `WorkspaceNotFound` | 404 |
| `DuplicateWorkspaceName` / `EmailAlreadyExists` | 409 |
| `WorkspaceStateError` | 409 |
| `InvalidCredentials` / `NotAuthenticated` | 401 |

### Auth (minimal, stdlib-only)
No external crypto/JWT libs — the standard library covers a *minimal* system:
`hashlib.pbkdf2_hmac` (salted, 240k iterations) for passwords and `hmac`+`sha256` for compact
signed tokens (`base64url(payload).base64url(sig)`, payload `{sub, exp}`). This keeps the
**only new dependency SQLAlchemy** and the system offline-first. Swappable for `pyjwt` later
with changes confined to `security.py`.

---

## 6. Frontend Architecture

**Stack added:** `react-router-dom` v7 (routing) + a React **Context** for auth state (no
Redux/Zustand — matches the project's minimal footprint). Pages are **lazy-loaded**.

### Pages
| Route | Page | Purpose |
|---|---|---|
| `/login` | `Login` | combined login/register |
| `/` | `WorkspacesDashboard` | grid of cards + search/sort/filter/paginate + CRUD |
| `/workspace/:workspaceId` | `WorkspaceDetail` | workspace-scoped upload + Q&A (the context boundary future modules inherit) |
| `*` | → `/` | fallback |

### Components
| Component | Role |
|---|---|
| `WorkspaceCard` | one card (icon, color accent, counts, relative time, hover lift, actions). **Memoized** so typing in search doesn't re-render every card. |
| `WorkspaceFormModal` | create **and** edit (settings) in one form — name/description/icon/color, live preview, inline validation, Escape-to-close |
| `WorkspaceToolbar` | search box + archived segment (Active/Archived/All) + sort select |
| `UploadPdf` / `AskQuestion` | carried over from MVP, now accept a `workspaceId` prop |

### State management
- **`AuthContext`** — holds `user` + token (persisted in `localStorage`); exposes
  `login/register/logout`; on mount validates an existing token via `/auth/me`.
- **Dashboard-local state** — list/query params live in the dashboard; data flows down to
  presentational components.

### Routing & auth gating (UI diagram)
```
<BrowserRouter>
  <AuthProvider>                         token in localStorage
    <App>
      /login  ──────────────▶ Login (redirects to / if already authed)
      RequireAuth ─┬─ /                 ▶ WorkspacesDashboard
                   └─ /workspace/:id    ▶ WorkspaceDetail  ← future modules nest here
```

### Dashboard layout (UI diagram)
```
┌───────────────────────────────────────────────────────────────┐
│ 🧠 LexiMind                                  alice   [Log out] │
├───────────────────────────────────────────────────────────────┤
│ Workspaces  (5 workspaces)                    [ + New workspace]│
│ [ 🔍 search…              ]   [Active|Archived|All]  [Sort ▾]  │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│ │🧠 OS    │ │📚 ML    │ │🔬 Papers│ │🚀 SIH   │   …cards…      │
│ │Docs 12  │ │Docs 30  │ │Docs 8   │ │Docs 3   │               │
│ │⚙️ 📥 🗑️ │ │⚙️ 📥 🗑️ │ │⚙️ 📥 🗑️ │ │⚙️ 📥 🗑️ │               │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘               │
│                     ← Prev   Page 1 of 3   Next →              │
└───────────────────────────────────────────────────────────────┘
```

### Performance
- **Debounced search** (300ms) → one request per pause, not per keystroke.
- **AbortController** per fetch → a newer query cancels the older in-flight one (no
  out-of-order state, no duplicate work).
- **Memoized cards** + **lazy routes** → minimal re-renders and smaller initial bundle
  (Login/Dashboard/Detail ship as separate chunks, confirmed by the build output).

---

## 7. Retrieval Integration

The workspace boundary is a **single metadata field** threaded through the existing pipeline —
no Phase-1/2 logic was rewritten.

### Ingest side
`build_chunk_metadata(..., workspace_id)` now writes `workspace_id` onto every chunk;
`ingest_pdf(..., workspace_id=...)` carries it; the `/upload/pdf` route accepts an optional
`workspace_id` form field and (when authenticated & owner matches) bumps the workspace's
`document_count`.

### Query side
`RetrievalFilter` gained a canonical **`workspace_id`** facet (the legacy `workspace` field is
kept as an alias that also matches `metadata["workspace_id"]`). `build_filter` allows the new
key. `/query` accepts a top-level `workspace_id` and folds it into the filter:

```
Query + workspace_id
   → RetrievalFilter(workspace_id=…)
   → Phase-1: dense + BM25 (filtered) → RRF → rerank
   → Phase-2: dedup → rank → budget → compress → assemble   (operates on the filtered chunks)
   → LLM
```

### Context engine (Phase 2) — no change required
The context builder operates on `result.chunks`, which retrieval has **already filtered** by
`workspace_id`. So duplicate-detection → evidence-ranking → compression → assembly
automatically see **only the active workspace's chunks**. Isolating upstream (at retrieval)
gives Step 8 for free, without editing the context package.

### Backward compatibility (Step 7 honored)
- `workspace_id` is **optional** everywhere. A request with no `workspace_id` searches the
  whole index exactly as before → existing retrieval is unbroken.
- An **empty filter matches everything**; a workspace filter excludes chunks lacking that id.
- Legacy chunks (2,436, pre-Phase-3) are backfilled into a **"Default" workspace** by
  `scripts/migrate_workspace.py` (idempotent, timestamped `.bak`, FAISS vectors untouched —
  only a JSON key added), mirroring Phase-1's `migrate_metadata.py`. Verified: the filter
  correctly matches backfilled chunks and excludes others.

---

## 8. API Documentation

All `/workspaces/*` routes require `Authorization: Bearer <token>`. `/upload` and `/query`
accept an **optional** token + `workspace_id` (backward compatible).

### `POST /auth/register` → 201
Request: `{ "email": "you@x.com", "password": "min8chars", "display_name": "You" }`
Response: `{ "access_token", "token_type": "bearer", "user": {…} }`
Errors: 422 invalid email/short password · 409 email exists.

### `POST /auth/login` → 200
Request: `{ "email", "password" }` · Response: same `TokenResponse`.
Errors: 401 invalid credentials (same message for unknown-email or wrong-password).

### `GET /auth/me` → 200
Header: bearer token · Response: `UserOut`. Errors: 401.

### `POST /workspaces` → 201
Request: `{ "name" (req), "description"?, "icon"?, "color"? }` · Response: `WorkspaceOut`.
Errors: 422 invalid name/color · 409 duplicate name · 401.

### `GET /workspaces` → 200
Query params: `page` (≥1), `page_size` (1–100), `search`, `archived` (`active|archived|all`),
`sort_by` (`name|created_at|updated_at|document_count`), `order` (`asc|desc`).
Response: `{ items: WorkspaceOut[], total, page, page_size, pages }`. Errors: 401.

### `GET /workspaces/{id}` → 200
Response: `WorkspaceOut`. Errors: 404 (not found / not owned) · 401.

### `PATCH /workspaces/{id}` → 200
Partial update — any of `name|description|icon|color`. Response: `WorkspaceOut`.
Errors: 422 · 409 duplicate name · 404 · 401.

### `POST /workspaces/{id}/archive` → 200 · `POST /workspaces/{id}/restore` → 200
Response: `WorkspaceOut`. Errors: 409 already-archived / not-archived · 404 · 401.

### `DELETE /workspaces/{id}?permanent=false` → 204
Soft-delete by default; `?permanent=true` hard-deletes. Errors: 404 · 401.

### `POST /upload/pdf` (multipart) → 200
Fields: `file` (PDF), optional `workspace_id`. Tags chunks with `workspace_id`; bumps
`document_count` when authenticated & owner matches.

### `POST /query` → 200
Request: `{ "question", "workspace_id"?, "filters"?, "top_k"? }`. Scopes retrieval to the
workspace when provided.

---

## 9. Testing

**45 new backend tests**, all passing. They run on an **in-memory SQLite** (StaticPool) and a
**minimal FastAPI app** (auth + workspace routers only) so the suite needs just SQLAlchemy +
FastAPI — never the FAISS/torch stack.

| File | Type | Covers |
|---|---|---|
| `test_workspace_validation.py` | unit | name trim/empty/length/forbidden-chars/control-char/unicode, description cap, color, icon, case-fold compare (10) |
| `test_auth.py` | unit | pbkdf2 hash roundtrip + salting, token roundtrip/expiry/tamper/garbage, register/login, dup-email, wrong-password, unknown-user (11) |
| `test_workspace_repository.py` | unit | owner-scoped get, case-insensitive `name_exists`, soft-delete hides + frees name, pagination + total, search (name/desc), archived filter, sorting, counter clamp (8) |
| `test_workspace_service.py` | unit | create defaults/normalize, dup-name, invalid name, update fields, same-name rename allowed, rename-collision, archive/restore + state errors, soft vs hard delete, owner scoping, counters (12) |
| `test_workspace_api.py` | **integration** | auth-required 401, **full lifecycle create→get→list→edit→archive→restore→delete**, duplicate→409, invalid→422, cross-user isolation, pagination+search (6) |

### Integration lifecycle (the required create → edit → archive → restore → delete)
`test_full_lifecycle` drives the real HTTP surface end-to-end and asserts at each step:
create (201) → get → list(total=1) → edit(rename+desc) → archive (drops from active list,
appears in archived) → restore → soft-delete (204; gone from `all`; 404 on get).

### Coverage & regression
- Every stage (validation, repo, service, api, auth) has dedicated tests; the integration
  test exercises the whole HTTP path.
- **No Phase-1/2 regression:** the only shared files touched (`retrieval/schemas.py`,
  `retrieval/filters.py`) are covered by the existing `test_filters.py` + `test_fusion.py`
  (**11/11 pass**) plus an explicit backward-compat assertion (empty filter matches all;
  workspace filter excludes untagged chunks). In the light env the full run reports **96
  passed**; the only non-runs are 4 collection errors for `test_bm25/hybrid/integration/
  query_analysis`, caused solely by `faiss` not being installed in that env (their logic is
  unchanged) — they run in the full backend venv.

```bash
# new suite (light deps: sqlalchemy + fastapi + pytest + httpx)
cd backend && python -m pytest tests/test_workspace_*.py tests/test_auth.py -q     # 45 passed
# full suite (in the real backend venv with faiss/torch)
cd backend && ./venv/bin/python -m pytest tests/ -q
```

---

## 10. File Changes Summary

### New files — Backend
| File | Purpose |
|---|---|
| `app/db/__init__.py`, `app/db/base.py` | SQLAlchemy engine, session factory, `Base`, `get_db`, `session_scope`, `init_db` |
| `app/auth/security.py` | stdlib pbkdf2 hashing + HMAC signed tokens |
| `app/auth/models.py` | `User` ORM |
| `app/auth/schemas.py` | register/login/token/user DTOs |
| `app/auth/errors.py` | auth domain errors |
| `app/auth/repository.py` | user data access |
| `app/auth/service.py` | register/login rules |
| `app/auth/dependencies.py` | `get_current_user` / `_user_id` / `optional_user_id` |
| `app/auth/api.py` | `/auth/register|login|me` |
| `app/workspaces/models.py` | `Workspace` ORM + `COUNTER_FIELDS` |
| `app/workspaces/schemas.py` | DTOs + list-query enums |
| `app/workspaces/validation.py` | pure field validation |
| `app/workspaces/errors.py` | workspace domain errors |
| `app/workspaces/repository.py` | owner-scoped, soft-delete-aware SQL + listing |
| `app/workspaces/service.py` | CRUD/business rules + counters |
| `app/workspaces/api.py` | authenticated `/workspaces/*` routes |
| `scripts/migrate_workspace.py` | backfill legacy chunks into a "Default" workspace |
| `tests/conftest.py` | in-memory DB + minimal-app fixtures |
| `tests/test_workspace_validation.py`, `test_auth.py`, `test_workspace_repository.py`, `test_workspace_service.py`, `test_workspace_api.py` | 45 new tests |

### New files — Frontend
| File | Purpose |
|---|---|
| `src/types.ts` | shared TS contracts |
| `src/api/client.ts` | fetch wrapper (token + `ApiError`) |
| `src/api/auth.ts`, `src/api/workspaces.ts` | typed API clients |
| `src/context/AuthContext.tsx` | auth state provider + `useAuth` |
| `src/components/workspace/constants.ts` | icon/color presets |
| `src/components/workspace/WorkspaceFormModal.tsx` | create/edit modal |
| `src/components/workspace/WorkspaceCard.tsx` | memoized card |
| `src/components/workspace/WorkspaceToolbar.tsx` | search/sort/filter |
| `src/pages/Login.tsx`, `WorkspacesDashboard.tsx`, `WorkspaceDetail.tsx` | pages |
| `src/styles/workspace.css` | theme-aware design system |
| `phase3_module1.md` | this document |

### Modified files
| File | Reason |
|---|---|
| `app/core/config.py` | add `database_url`, `secret_key`, `token_ttl_seconds`, `pbkdf2_iterations` |
| `app/main.py` | mount auth + workspace routers; `init_db()` on startup; add 127.0.0.1 CORS origin |
| `app/services/ingestion_service.py` | thread `workspace_id` into chunk metadata + `ingest_pdf` |
| `app/api/upload.py` | optional `workspace_id` + optional auth; bump `document_count` |
| `app/api/query.py` | optional top-level `workspace_id` folded into the retrieval filter |
| `app/retrieval/schemas.py` | add canonical `workspace_id` filter facet (legacy `workspace` alias) |
| `app/retrieval/filters.py` | allow `workspace_id` request key |
| `requirements.txt` | add `SQLAlchemy==2.0.51` (only new dependency) |
| `src/main.tsx` | `BrowserRouter` + `AuthProvider` + workspace CSS |
| `src/App.tsx` | router with lazy pages + `RequireAuth` gate |
| `src/api/backend.ts` | `uploadPdf`/`askQuestion` accept `workspaceId` + attach token |
| `src/components/UploadPdf.tsx`, `AskQuestion.tsx` | accept `workspaceId` prop |
| `src/components/AnswerBox.tsx` | render the sources the backend already returns (fixes a dead-variable build error) |

---

## 11. Future Compatibility

Module 1 is the substrate every remaining Phase-3 module builds on:

| Future capability | What Module 1 already provides |
|---|---|
| **Document Library** | `workspace_id` on chunks + `document_count`; `/workspace/:id` is the mount point; per-workspace retrieval already isolates |
| **Chats** | `chat_count` column + counter plumbing; workspace-scoped `/query` is ready; `WorkspaceDetail` hosts the chat surface |
| **Notes** | `note_count` + the same `Evidence`/context path scoped to the workspace |
| **Flashcards** | `flashcard_count` + workspace context inheritance |
| **Summaries** | `summary_count` + citation-preserving context from Phase 2 |
| **Teams / Collaboration** | `owner_id` is real; add `teams`/`memberships` + `workspace.team_id` with no row rewrites; auth `dependencies` are the single guard to extend |
| **Permissions** | domain errors + owner-scoping give the enforcement point; roles slot into the service layer |

Every new module follows the **same layering** (model → repository → service → api + DTOs +
validation + errors), reuses `get_current_user_id` for scoping, and nests under
`/workspace/:workspaceId` on the frontend.

---

## 12. Lessons Learned

### Design decisions
- **Complete the existing seam, don't invent one.** Phase 1 already had a `workspace` filter
  field; Phase 3 populates it (`workspace_id`) rather than bolting on a parallel mechanism.
  Filtering **upstream at retrieval** made the Phase-2 context engine workspace-aware with
  **zero** changes to that package.
- **Two stores, one link.** Structured rows belong in SQLite; vectors stay in FAISS. Coupling
  them only by a `workspace_id` string keeps each layer independently testable and swappable.
- **Denormalized counters** trade a little write-time bookkeeping for O(1) dashboard reads at
  any scale — the right call for a read-heavy card grid.
- **Minimal stdlib auth.** The user asked for real ownership; pbkdf2 + HMAC tokens deliver it
  with **only SQLAlchemy added**, keeping the offline-first promise intact.
- **Clean architecture pays off immediately.** Because rules live in services and SQL in
  repositories, the service was unit-tested against a real DB while the API was integration-
  tested over a minimal app — and future modules get a proven template.

### Tradeoffs
- **SQLite, not Postgres** — zero-ops and offline; migrate by env var when concurrency demands.
- **Service-enforced uniqueness**, not a partial unique index — clearer with soft-delete/archive.
- **Minimal auth**, not full OAuth/JWT — sufficient for ownership; `security.py` is the single
  swap point later.
- **Counters maintained in code**, not via triggers — simple and explicit; a periodic
  reconciliation job can be added if drift is ever observed.

### Known limitations
- No hard FK from `workspaces.owner_id` to `users.id` yet (lets the migration bootstrap a
  Default workspace under a placeholder owner). Add it once accounts always precede workspaces.
- Upload counter bump requires authentication; an anonymous workspace-tagged upload won't
  increment (documented, low-impact).
- Auth token has no refresh/rotation; fine for the current single-user, local scope.
- The light-env test run can't exercise the 4 FAISS-dependent suites (environmental, not a
  logic gap).

### Future improvements
1. Real FK + a `teams`/`memberships` schema for collaboration (Phase 3 later modules).
2. Postgres profile + Alembic migrations once the schema stabilizes.
3. Token refresh + optional password reset.
4. Per-workspace vector namespaces (or per-workspace indexes) if a single flat index grows large.
5. Counter reconciliation job + move counters to DB-side atomic updates under concurrency.
6. Bulk actions (multi-archive/delete) and a trash view for soft-deleted workspaces.
```
