# Phase 5 · Module 1 — Audio & Video Processing Engine

> LexiMind's evolution from **static knowledge** (documents, images, diagrams, tables) to
> **temporal knowledge** (lectures, meetings, podcasts, tutorials, recorded classes, videos).
> This module is the ingestion foundation for every future Audio/Video AI capability. It transforms
> raw media into structured, timestamp-aware knowledge while staying fully asynchronous and
> **without touching** the Phase-1 Retrieval Engine, Phase-2 Context Engine, or their Phase-4
> multimodal evolutions.

---

## 1. Module Overview

### Why temporal media processing is needed
Everything LexiMind understood before this module was **static**: a PDF page, an image, a table — a
unit of knowledge with a *position* (page, bbox) but no *time*. Recordings are different. A lecture's
meaning is distributed across a **timeline**: who spoke, when a slide changed, what was on screen at
12:04, which scene a diagram appeared in. To make recordings first-class knowledge we must decompose
them into **temporal units** anchored to `[start_ms, end_ms)` windows.

### Static vs temporal knowledge
| | Static (Phases 1–4) | Temporal (this module) |
|---|---|---|
| Atom | chunk / page / figure | transcript segment / scene / frame / speaker turn |
| Anchor | page number, bbox | `start_ms`, `end_ms`, speaker, scene |
| Source | text extraction, OCR | speech-to-text, diarization, scene detection, frame OCR |
| Retrieval key (future) | semantic similarity | similarity **+ time + speaker + scene** |

### Overall architecture
A new **`app/media/`** domain, structurally identical to the Phase-4 `app/ingestion/` module (same
layered files, same injected-engine + async-runner + inline-test pattern). It is a **separate async
layer** attached to an existing `Document` row (created with `media_type` ∈ {audio, video}). It never
modifies text upload/retrieval; its temporal chunks land in a **future embedding queue**
(`embedding_status="pending"`), exactly like `MultimodalChunk`.

---

## 2. Previous Architecture

Before this module, ingestion looked like:

```
Upload (PDF/image) → validate → classify → OCR (cached) → extract images/tables/figures
                   → multimodal chunks (embedding_status="pending") → metadata → Ready
```

**Limitations for media:**
- `documents` upload accepted **`pdf` only** (`supported_document_extensions`), and its ingest ran
  PDF text-extraction → FAISS. Feeding it an `mp4` was impossible and meaningless.
- No concept of **time**: chunks carried `page_number`, never `start_ms`/`end_ms`.
- No speech-to-text, no speakers, no scenes, no frames, no subtitles.
- The `Document` model *anticipated* this (`media_type`, `mime_type`, free-form status columns whose
  comments literally say "future multimodal support (images / audio / video)") — the columns existed;
  the pipeline did not.

---

## 3. New Architecture

```
        Upload Audio / Video
                 │
          Media Validation            (format registry, size, duration)
                 │
        Metadata Extraction           (ffprobe: duration, codecs, fps, sample rate)
                 │
       Media Classification           (lecture / meeting / podcast / tutorial / …)
                 │
          Speech-to-Text              (Whisper → transcript segments + word timings)
                 │
        Speaker Diarization           (pyannote → speakers + conversation turns)
                 │
         Scene Detection              (PySceneDetect → scene boundaries)   ┐ video
                 │                                                          │ only
        Frame Extraction              (OpenCV → representative frames)      │
                 │                                                          │
       OCR From Frames                (REUSES Phase-4 OCR backend, cached)  │
                 │                                                          │
      Subtitle Extraction             (ffmpeg → embedded/closed captions)   ┘
                 │
      Temporal Chunk Generation       (transcript/speaker/scene/subtitle/ocr/frame)
                 │
        Temporal Metadata             (duration, speakers, speech-rate, latencies…)
                 │
             Storage                  (assets/{ws}/{doc}/frames|subtitles/…)
                 │
              Ready
```

Everything runs **off the request path** in a background runner; the client polls
`GET /workspaces/{id}/media/{doc}/status`. Audio files skip the video-only stages automatically.

**Component diagram (backend):**
```
             HTTP (api.py)  ──►  MediaService (service.py)  ──►  MediaRepository (repository.py)  ──► SQLite
                                     │  ▲                             (9 media tables)
        MediaRunner (runner.py) ─────┘  │
                                        │ injects
                                   MediaEngine (engines.py)
                       Fake (tests) │ Pipeline (ffmpeg/whisper/pyannote/scenedetect/opencv, lazy)
                                        │ reuses
                       app.ingestion.engines OCR backend  +  app.ingestion.OcrResult cache
```

---

## 4. Processing Pipeline

The engine emits a typed **event stream**; the service consumes and persists it (identical contract
style to `MultimodalEngine`). Cross-references are resolved in a single finalization pass.

| Stage | Producer | Persists | Notes |
|---|---|---|---|
| **Speech-to-Text** | `faster-whisper` | `TranscriptSegment` (start/end/text/confidence/words) | language detection, word-level timings, `no_speech_prob`; never re-transcribed for an unchanged file (file-hash guard) |
| **Speaker Diarization** | `pyannote.audio` | `Speaker` + `SpeakerTurn` | speaking duration, turn count, conversation timeline; segments resolve `speaker_id` by label; graceful single-speaker fallback |
| **Scene Detection** | `PySceneDetect` | `Scene` (start/end/duration/rep-frame) | scene boundaries as independent knowledge units |
| **Frame Extraction** | `OpenCV` | `MediaFrame` (timestamp/size/hash/keyframe/path) | scene-boundary or periodic; thumbnails to disk |
| **OCR from Frames** | **Phase-4 OCR backend (reused)** | `MediaFrame.ocr_text` + cache | on-screen slides/whiteboard text; cached in `OcrResult` — never re-run |
| **Subtitle Extraction** | `ffmpeg` | `Subtitle` | embedded/closed captions (WebVTT parser) |
| **Temporal Chunking** | pure `chunking.py` | `MediaChunk` | speaker-coherent transcript windows + scene/subtitle/ocr/frame chunks |

**Background jobs:** `MediaRunner` (ThreadPoolExecutor) opens its own DB session and calls
`process_now`; retry/cancel are status transitions the worker observes (`clear_job_assets` gives a
clean slate on reprocess while **preserving the OCR cache**).

**Progress tracking:** every `stage` event updates `MediaJob.stage`/`progress`; a `MediaProcessingLog`
row is written per milestone; per-stage latencies are captured for observability.

---

## 5. Storage & Metadata Design

### Schemas (9 new tables)
`MediaJob`, `TranscriptSegment`, `Speaker`, `SpeakerTurn`, `MediaFrame`, `Scene`, `Subtitle`,
`MediaChunk`, `MediaProcessingLog`.

### Relationships
```
Document (media_type=audio|video)
   └── MediaJob (1 latest per document)
         ├── TranscriptSegment  (speaker_id → Speaker)
         ├── Speaker ──< SpeakerTurn
         ├── Scene ──< MediaFrame (scene_id)      Scene.representative_frame_id → MediaFrame
         ├── Subtitle
         ├── MediaChunk (chunk_type, start_ms/end_ms, speaker_id, scene_id, asset_id)
         └── MediaProcessingLog
Frame OCR cache → app.ingestion.OcrResult  (reused, keyed by document + frame_index + content_hash)
```

### Indexes (scalability)
- `MediaJob`: `(workspace_id, document_id)`, `status`, `owner_id`.
- Every asset table: `(document_id, start_ms)` (or `timestamp_ms`) — timeline scans are range scans.
- `MediaChunk`: `(document_id, chunk_type)`, `(document_id, start_ms)`, `embedding_status` (future
  embedding queue drains by this index).

### Storage hierarchy (reuses Phase-4 `AssetStorage`)
```
assets/{workspace_id}/{document_id}/
    frames/{frame_id}.jpg
    subtitles/{id}.vtt
    audio/{id}.wav          (future: normalized track)
    transcript/{id}.json    (future: raw dump)
```
Local filesystem behind the `AssetStorage` interface → swap to S3/GCS in one place for **both**
document and media assets.

### Metadata
`metadata.py` assembles the canonical temporal-metadata dict (duration, language, speaker/scene/
frame/subtitle/segment counts, transcript length, **average speech rate (wpm)**, codecs, processing
time, per-stage latencies, cache hits, pipeline version) so downstream modules consume it directly.

---

## 6. Backend Architecture

Mirrors the project's per-domain layered contract exactly:

- **`models.py`** — 9 SQLAlchemy tables on the shared `Base`; naive-UTC timestamps (SQLite convention).
- **`schemas.py`** — Pydantic DTOs (`from_attributes`).
- **`validation.py`** — pure format registry (audio/video), size + duration guards; self-contained
  (does not touch `documents.validation`).
- **`classification.py`** — pure, model-free category heuristics; swappable for a model later.
- **`errors.py`** — transport-agnostic, each carries `status_code`.
- **`repository.py`** — the **only** SQL for media tables; frame-OCR cache delegates to
  `IngestionRepository` (no duplicate cache). Includes `job_status()` — reads *only* the status
  column for cancellation checks (avoids the "refresh clobbers counters" gotcha from Module 2).
- **`service.py`** — `upload` (create media `Document` + persist bytes + enqueue), `process_now`
  (staged pipeline + finalization pass), retry/cancel, all queries. **Failure recovery** keeps
  partial assets and records the error; cancellation is honored between stages.
- **`engines.py`** — the **only** bridge to A/V libraries; injected + lazy. `FakeMediaEngine`
  (deterministic, drives every path) + `PipelineMediaEngine` (ffmpeg/whisper/pyannote/scenedetect/
  opencv, each degrading gracefully; **frame OCR calls the shared ingestion backend**).
- **`interfaces.py`** — declared retrieval/context seams (`TemporalUnit`, `to_temporal_units`,
  `to_context_evidence`), intentionally **not wired**.
- **`runner.py`** — `MediaRunner` (threadpool prod) / `InlineRunner` (tests) / `DeferredRunner`.
- **`api.py`** — thin FastAPI router; heavy runner injected via `Depends(get_media_runner)` so tests
  override it.

**Caching:** unchanged file (file-hash) → completed job returned, never re-transcribed. Unchanged
frame content (content-hash) → OCR served from `OcrResult`, never re-OCR'd.

**Error handling:** domain errors → `status_code` → HTTP (415 unsupported, 413 too large, 422 empty/
invalid, 404 not found, 409 illegal transition).

---

## 7. Frontend Architecture

- **`api/media.ts`** — typed client (self-contained types), XHR upload with progress, `pollMedia`
  until terminal, all read endpoints, retry/cancel, `fmtTime`/`frameThumbnailUrl` helpers.
- **`pages/MediaWorkspace.tsx`** — the **Audio & Video Studio** (`/workspace/:id/media`): upload
  center (drag a recording), a recordings library sidebar, a live processing dashboard, then the
  media detail once complete.
- **`components/media/MediaProgress.tsx`** — the processing dashboard: ordered pipeline stages
  (video-only stages greyed for audio), progress bar, status badge, error surface + **retry/cancel**.
- **`components/media/MediaDetail.tsx`** — tabbed viewer: **Transcript** (time + colored speaker +
  text), **Speakers** (profile cards + a proportional conversation timeline), **Scenes & Frames**
  (thumbnail grid with OCR markers), **Subtitles**, **Temporal Chunks** (filterable, showing the
  `pending` embedding queue), **Metadata** table.
- **State management:** local React state + `AbortController`-scoped polling; no new dependency.
- **Routing:** lazy route in `App.tsx`; CTA added on `WorkspaceDetail`.
- **`styles/media.css`** — theme-aware, reuses shared tokens (`--primary`, `--border`, `--surface`…).

---

## 8. Future Integration

This module deliberately **stops at ingestion**. It prepares — but does not wire — the seams for:

- **Temporal Intelligence / Audio-Video Retrieval** — `interfaces.to_temporal_units()` adapts
  `MediaChunk`s into `TemporalUnit`s whose `modality` matches the `mmretrieval` vocabulary, so a
  future `TemporalRetriever` fuses cleanly with text/OCR/image hits. The `embedding_status="pending"`
  queue is the drain point for a future embedding job.
- **Timeline-aware Context Engineering** — `interfaces.to_context_evidence()` shapes units with
  `start_ms`/`end_ms`/`speaker`/`scene`, so a future assembler can cite *"at 12:04, SPEAKER_01
  said…"* without changing dedup/ranking/compression/assembly/citation behaviour.
- **Knowledge Graph** — speakers, scenes, and turns are first-class rows ready to become nodes/edges.
- **AI Agents / Meeting Intelligence / Lecture Intelligence** — action-items, chapters, and summaries
  build directly on transcript segments + speaker turns + scenes.

Retrieval, Context, and Multimodal Workspace behaviour are **unchanged** by this module.

---

## 9. API Documentation

All routes are authenticated (`Authorization: Bearer`) and workspace-scoped under
`/workspaces/{workspace_id}/media`.

| Method | Path | Body / Query | Response | Errors |
|---|---|---|---|---|
| POST | `` (upload) | multipart `file` | `201 UploadResponse{document_id,filename,media_kind,job}` | 415 unsupported, 413 too large, 422 empty |
| POST | `/{doc}/process` | `{force?:bool}` | `202 MediaJob` | 404, 415 |
| GET | `/{doc}/status` | — | `MediaJob | null` | 404 |
| GET | `/{doc}/transcript` | `?speaker_id=` | `TranscriptResponse` | 404 |
| GET | `/{doc}/speakers` | — | `SpeakerTimelineResponse{speakers,timeline}` | 404 |
| GET | `/{doc}/frames` | `?scene_id=` | `MediaFrame[]` | 404 |
| GET | `/{doc}/frames/{frame}/thumbnail` | — | `image/jpeg` | 404 |
| GET | `/{doc}/scenes` | — | `Scene[]` | 404 |
| GET | `/{doc}/subtitles` | — | `Subtitle[]` | 404 |
| GET | `/{doc}/ocr` | — | `OcrResponse{ocr_frame_count,frames}` | 404 |
| GET | `/{doc}/chunks` | `?chunk_type=` | `MediaChunk[]` | 404 |
| GET | `/{doc}/metadata` | — | temporal-metadata dict | 404 |
| GET | `/jobs/{job}` | — | `MediaJobDetail{…,logs}` | 404 |
| POST | `/jobs/{job}/retry` | — | `MediaJob` | 404, 409 |
| POST | `/jobs/{job}/cancel` | — | `MediaJob` | 404, 409 |

**Validation** is enforced *before* any heavy work: extension against the audio/video registry, size
against `max_media_bytes` (2 GB default), duration against `max_media_duration_ms` (6 h default).
Errors carry the backend's `detail` string for the UI.

**Example — upload & poll:**
```
POST /workspaces/ws_1/media           (multipart file=lecture.mp4)
 → 201 { document_id: "doc_ab12", media_kind: "video", job: { status: "queued", ... } }
GET  /workspaces/ws_1/media/doc_ab12/status
 → 200 { status: "processing", stage: "transcription", progress: 30, ... }
 → 200 { status: "completed", segment_count: 42, speaker_count: 2, scene_count: 9, ... }
```

---

## 10. Performance Optimizations

- **Fully asynchronous** — heavy transcription/diarization/frame work never blocks the API; a
  threadpool runner processes off the request path.
- **Two-level caching** — file-hash guard skips re-processing an unchanged recording entirely;
  content-hash frame-OCR cache (reused `OcrResult`) never re-OCRs an identical frame. Cache hits are
  counted in metadata.
- **Streaming persistence** — frame bytes are written to disk as they stream; only lightweight
  metadata is buffered for the finalization pass → bounded memory even for long videos.
- **Sampling caps** — `frame_interval_ms` and `max_frames_per_media` bound frame work; scene-boundary
  frames preferred over dense periodic sampling.
- **Lazy singletons** — Whisper/pyannote models load once and are reused across jobs; imports are
  lazy so the package (and all tests) run without any A/V library installed.
- **Indexed range scans** — timeline reads hit `(document_id, start_ms)` indexes.
- **Incremental / resumable** — `completed_stages` bookkeeping + `clear_job_assets` (OCR cache
  preserved) support reprocessing without losing recognized text.
- **GPU acceleration** — `PipelineMediaEngine` selects `device="auto"` for Whisper (int8), using GPU
  when present, degrading to CPU otherwise.

---

## 11. Testing

Everything runs **offline** — no ffmpeg/whisper/pyannote/opencv — via the injected `FakeMediaEngine`
and the `InlineRunner` (wired in `conftest.py`, mirroring the ingestion suite).

**Unit tests (`tests/test_media_unit.py`)** — validation (formats/size/duration), classification
(keyword + structural fallback), temporal chunking (speaker-coherent windows, word-budget splits, all
modalities, running index), metadata assembly + speech rate, `FakeMediaEngine` event contract
(video full contract; audio skips video stages), WebVTT/timestamp parsing, and the interface seam
adapters.

**Integration tests (`tests/test_media_api.py`)** — the full lifecycle over HTTP:
```
upload → (InlineRunner) transcription → diarization → scenes → frames → OCR → subtitles →
temporal chunks → metadata → status=completed
```
plus per-output endpoints (transcript, speaker-filtered transcript, speaker timeline, scenes+frames,
scene-scoped frames, frame thumbnail bytes, subtitles, OCR, chunks + filter, metadata), media
appearing as a `media_type` document, validation errors (415/422), job detail logs, retry-conflict
(409), **cancel** of a queued job (via `DeferredRunner` override), and force-reprocess.

**Coverage / results**
- New: **39** media tests (`test_media_unit.py` + `test_media_api.py`) — all pass.
- Regression: full suite **458 passed** (419 pre-existing + 39 new), `test_reranker`/`test_eval`
  excluded per project convention (require torch/reranker model). **Zero regressions** across
  Phases 1–4.
- Frontend: `tsc -b` clean; `vite build` succeeds (`MediaWorkspace` chunk emitted).

---

## 12. File Changes Summary

### New files — backend (`backend/app/media/`)
| File | Purpose |
|---|---|
| `__init__.py` | domain docstring / package |
| `models.py` | 9 temporal ORM tables |
| `schemas.py` | Pydantic DTOs |
| `validation.py` | audio/video format registry + size/duration guards |
| `classification.py` | pure media-category heuristics |
| `errors.py` | transport-agnostic domain errors |
| `storage.py` | media asset storage (reuses `AssetStorage`) |
| `chunking.py` | pure temporal chunk builder |
| `metadata.py` | pure temporal-metadata assembly |
| `engines.py` | injected `FakeMediaEngine` + `PipelineMediaEngine` (lazy A/V libs; reuses OCR) |
| `repository.py` | all SQL for media tables (frame-OCR cache reused) |
| `service.py` | staged async pipeline + upload + finalization |
| `interfaces.py` | future retrieval/context seams (declared, not wired) |
| `runner.py` | threadpool + inline + deferred runners |
| `api.py` | authenticated routes under `/workspaces/{id}/media` |

### New files — tests & frontend & docs
`backend/tests/test_media_unit.py`, `backend/tests/test_media_api.py`,
`frontend/.../api/media.ts`, `frontend/.../pages/MediaWorkspace.tsx`,
`frontend/.../components/media/MediaProgress.tsx`,
`frontend/.../components/media/MediaDetail.tsx`, `frontend/.../styles/media.css`,
`phase5_module1.md`.

### Modified files (registration/wiring only — no behavior change)
| File | Change |
|---|---|
| `backend/app/core/config.py` | media settings (`max_media_bytes`, `max_media_duration_ms`, whisper/frame/scene knobs) |
| `backend/app/db/base.py` | register `app.media.models` in `init_db()` |
| `backend/app/main.py` | mount `media_router` |
| `backend/tests/conftest.py` | register media models + mount router + override `get_media_runner` with `InlineRunner(FakeMediaEngine)` |
| `frontend/.../App.tsx` | lazy `/workspace/:id/media` route |
| `frontend/.../pages/WorkspaceDetail.tsx` | "🎬 Audio & Video" CTA |

---

## 13. Lessons Learned

**Architecture decisions**
- *Reuse the `Document` row as the durable media identity.* The model already carried `media_type`/
  `mime_type` and free-form status columns explicitly designed for audio/video. A media file is a
  `Document(media_type=video)`; the `MediaJob` is the temporal analogue of `ProcessingJob`. Zero
  changes to the document schema; recordings appear in the library for free.
- *Mirror `app/ingestion/` exactly.* Copying the injected-engine + async-runner + inline-test shape
  meant the module slotted into `conftest`, `init_db`, and `main` with one line each and behaved
  predictably from day one.
- *Reuse, never fork, OCR.* Frame OCR calls `app.ingestion.engines` and caches in `OcrResult` — one
  OCR backend, one cache, for both documents and video frames.
- *Finalize cross-references in one pass.* Buffering lightweight event metadata (while streaming
  frame *bytes* to disk immediately) let me resolve segment→speaker, frame→scene, and
  scene→representative-frame after all events arrived — clean and memory-bounded.

**Tradeoffs**
- Heavy A/V libraries (whisper/pyannote/scenedetect/opencv/ffmpeg) are **lazy and optional**,
  matching how `PipelineMultimodalEngine` ships PaddleOCR today. The package imports and the entire
  test suite run with none of them installed; the real code path degrades gracefully per-stage
  (audio-only box still transcribes without OpenCV). The cost: the production engine is exercised by
  contract (`FakeMediaEngine`) here, not by an end-to-end transcription in CI.
- Frame-OCR reuses `OcrResult` by treating `frame_index` as the "page number." Pragmatic and DRY;
  a dedicated media-OCR cache could be introduced later if frame identity needs to diverge from pages.

**Known limitations**
- Live streams / YouTube / cloud imports are **declared** in the registry (`FUTURE_SOURCES`) but not
  processed yet.
- Speaker *identification* (mapping `SPEAKER_00` → a person) is scaffolded (`Speaker.display_name`)
  but not implemented.
- Media chunks are **not embedded/retrievable** yet — that is the next module, by design.

**Future improvements**
- Drain the `embedding_status="pending"` queue into a temporal vector index and wire
  `interfaces.to_temporal_units()` into `mmretrieval`.
- Chaptering, action-item extraction, and meeting/lecture summaries over transcript + turns + scenes.
- Real GPU-batched Whisper/pyannote runs in a worker with progress callbacks feeding per-stage
  latency into the observability metrics already captured on `MediaJob`.
