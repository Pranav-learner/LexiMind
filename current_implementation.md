# LexiMind — Current Implementation

> Last updated: June 2026
> Status: **Phase 0 — Working MVP (RAG Pipeline Functional)**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Backend — Detailed Breakdown](#3-backend--detailed-breakdown)
   - [3.1 FastAPI Application Entry Point](#31-fastapi-application-entry-point)
   - [3.2 API Layer (Routes)](#32-api-layer-routes)
   - [3.3 Services Layer](#33-services-layer)
4. [Frontend — Detailed Breakdown](#4-frontend--detailed-breakdown)
   - [4.1 Tech Stack](#41-tech-stack)
   - [4.2 API Client](#42-api-client)
   - [4.3 Components](#43-components)
   - [4.4 Pages](#44-pages)
5. [End-to-End Data Flow](#5-end-to-end-data-flow)
6. [Persisted Artifacts on Disk](#6-persisted-artifacts-on-disk)
7. [What Is NOT Yet Implemented](#7-what-is-not-yet-implemented)
8. [Current Limitations](#8-current-limitations)
9. [Development Roadmap (Phases)](#9-development-roadmap-phases)

---

## 1. Project Overview

**LexiMind** is an Offline-First Multimodal Knowledge Operating System.  
It is NOT a chatbot. It is a private AI-powered knowledge workspace — like NotebookLM + Obsidian + Perplexity combined.

The current implementation is a **functional MVP** that implements a complete RAG (Retrieval-Augmented Generation) pipeline:

```
PDF Upload → Text Extraction → Cleaning → Chunking → Embedding → FAISS Storage
                                                                          ↓
User Question → Embed → FAISS Search → Top-K Chunks → Ollama (Llama 3) → Answer + Citations
```

Everything runs **100% locally** — no cloud APIs, no subscriptions, no internet required.

---

## 2. Repository Structure

```
LexiMind/
├── MASTER_CONTEXT.md              # Project vision, architecture decisions, roadmap
├── current_implementation.md      # This file
│
├── backend/
│   ├── requirements.txt           # Python dependencies
│   ├── vector_index.faiss         # Persisted FAISS vector index (~3.7 MB)
│   ├── vector_metadata.json       # Persisted chunk metadata (~6 MB)
│   ├── uploaded_pdfs/             # Uploaded PDF files stored here
│   ├── venv/                      # Python virtual environment
│   └── app/
│       ├── main.py                # FastAPI app entrypoint + CORS setup
│       ├── core/
│       │   └── config.py          # (empty — reserved for future config)
│       ├── api/
│       │   ├── health.py          # GET /health — liveness check
│       │   ├── upload.py          # POST /upload/pdf — PDF ingestion endpoint
│       │   └── query.py           # POST /query — question answering endpoint
│       └── services/
│           ├── pdf_service.py     # PDF extraction + cleaning + heading detection
│           ├── chunking_service.py # Semantic + size-aware chunking
│           ├── embedding_service.py # SentenceTransformer embeddings
│           ├── vector_store.py    # FAISS vector store (add/search/save/load)
│           └── answer_service.py  # Ollama LLM call + citation formatting
│
└── frontend/
    └── leximind-frontend/
        ├── package.json
        ├── vite.config.ts
        ├── tsconfig.json
        ├── index.html
        └── src/
            ├── main.tsx           # React app entry point
            ├── App.tsx            # Root component (renders Home)
            ├── index.css          # Global styles
            ├── api/
            │   └── backend.ts     # Typed fetch wrappers for backend API
            ├── components/
            │   ├── UploadPdf.tsx  # PDF file picker + upload UI
            │   ├── AskQuestion.tsx # Question input + answer trigger
            │   └── AnswerBox.tsx  # Renders LLM answer + sources
            └── pages/
                └── Home.tsx       # Main page layout
```

---

## 3. Backend — Detailed Breakdown

**Runtime:** Python 3.x + FastAPI + Uvicorn  
**Start command:** `uvicorn app.main:app --reload` (run from `/backend`)

### 3.1 FastAPI Application Entry Point

**File:** `backend/app/main.py`

- Creates the `FastAPI` app with title `"LexiMind API"`
- Configures **CORS middleware** to allow requests from `http://localhost:5173` (Vite dev server)
- Registers three routers: `health`, `upload`, `query`
- Root endpoint `GET /` returns a heartbeat JSON message

```python
# Registered routers
app.include_router(health_router)   # /health
app.include_router(upload_router)   # /upload/pdf
app.include_router(query_router)    # /query
```

---

### 3.2 API Layer (Routes)

#### `GET /health` — `api/health.py`
Simple liveness check. Returns `{ "status": "OK", "service": "Bookture API" }`.

---

#### `POST /upload/pdf` — `api/upload.py`

This is the **document ingestion pipeline** entry point.

**What it does step by step:**
1. Accepts a multipart `UploadFile`
2. Saves the raw PDF to `uploaded_pdfs/<filename>`
3. Calls `extract_text_from_pdf()` → returns structured pages with paragraphs + headings
4. Calls `chunk_text()` → returns semantically-aware chunks with metadata
5. For each chunk:
   - Calls `generate_embedding(chunk["text"])` → 384-dim float vector
   - Calls `vector_store.add(embedding, metadata)` → stores in FAISS + metadata list
   - Calls `vector_store.save()` → persists both `.faiss` index and `.json` metadata to disk
6. Returns:
```json
{
  "filename": "example.pdf",
  "pages_extracted": 12,
  "total_chunks": 47,
  "message": "PDF processed and indexed successfully"
}
```

> **Note:** The `VectorStore` instance is a **module-level global** in `upload.py`, shared with `query.py` via import.

---

#### `POST /query` — `api/query.py`

This is the **question answering pipeline** entry point.

**Request body:**
```json
{ "question": "What is machine learning?" }
```

**What it does step by step:**
1. Receives `QueryRequest` (Pydantic model with `question: str`)
2. Embeds the question: `generate_embedding(req.question)` → 384-dim vector
3. Searches FAISS: `vector_store.search(query_embedding, top_k=5)` → top 5 relevant chunks
4. Calls `generate_answer(question, chunks)` → sends prompt to Ollama, returns answer text
5. Calls `format_sources(chunks)` → formats citations
6. Returns:
```json
{
  "question": "...",
  "answer": "Answer:\n...\n\nSources:\n...",
  "sources": "- filename.pdf | Page 3 | Paragraphs 2–4 | Section: Intro | Score: 0.8312"
}
```

---

### 3.3 Services Layer

#### `pdf_service.py` — PDF Extraction + Cleaning

**Dependencies:** `pdfplumber`, `re`, `collections.Counter`

**Two main functions:**

**`extract_text_from_pdf(file_path)`**
- Opens PDF with `pdfplumber`
- For each page, extracts raw text and splits by `\n` into lines
- Groups consecutive non-empty lines into **paragraphs** (blank-line delimited)
- Detects whether each paragraph is a **heading** via `is_heading(text)`
- Returns list of structured pages:
```python
[
  {
    "page_number": 1,
    "paragraphs": [
      { "paragraph_index": 0, "text": "...", "is_heading": False },
      { "paragraph_index": 1, "text": "Introduction", "is_heading": True },
    ]
  },
  ...
]
```
- After extraction, calls `clean_extracted_text()` to remove noise

**`is_heading(text)`** — Heuristic heading detector:
- Returns `False` if text is longer than 15 words (body text)
- Returns `False` if text ends with a period
- Returns `True` if text matches numbered patterns like `1.`, `Phase 3`, `Chapter 2`
- Returns `True` if text ends with `:`
- Returns `True` if >60% of words are capitalized
- Returns `True` if text is all uppercase

**`clean_extracted_text(pages)`** — Noise removal:
- Counts how often each non-heading paragraph appears across all pages
- Marks paragraphs appearing in >50% of pages as **repeated** (headers/footers) → removes them
- Removes paragraphs containing URLs, `www.`, or `@` (email/web noise)
- Removes short non-heading paragraphs with fewer than 10 words (page numbers, labels, etc.)
- Returns cleaned page list (pages with zero surviving paragraphs are dropped)

---

#### `chunking_service.py` — Semantic Chunking

**Dependencies:** `numpy`, `embedding_service`

**Constants:**
- `MAX_WORDS = 250` — max words per chunk before forcing a split
- `SIM_THRESHOLD = 0.75` — cosine similarity threshold; below this → new chunk

**`chunk_text(pages)`**

For each page, iterates through non-heading paragraphs and applies a **semantic + size-aware chunking strategy**:

1. Tracks current accumulated chunk text and the last paragraph's embedding
2. For each new paragraph:
   - Embeds the paragraph
   - Computes cosine similarity with the previous paragraph's embedding
   - **Splits** if current word count + new paragraph words > `MAX_WORDS` (size limit)
   - **Splits** if cosine similarity < `0.75` (topic shift detected)
   - **Merges** otherwise (paragraphs on same topic)
3. Each finalized chunk stores:
```python
{
  "chunk_index": 5,
  "page_number": 3,
  "section_heading": "Introduction to Machine Learning",  # last seen heading
  "start_paragraph": 2,
  "end_paragraph": 4,
  "text": "merged paragraph text..."
}
```

**`cosine_similarity(vec1, vec2)`** — Utility function using NumPy dot product.

> **Key design decision:** Each paragraph is embedded *during chunking* to decide similarity, meaning embedding runs twice — once during chunking, once for storage. This is the current approach and is a known inefficiency.

---

#### `embedding_service.py` — Text Embeddings

**Dependencies:** `sentence_transformers`

**Model:** `all-MiniLM-L6-v2`
- Small, fast, high-quality for semantic similarity
- Outputs **384-dimensional** float vectors
- Runs fully locally — no network calls

**`generate_embedding(text: str) -> list`**
- Encodes text with `model.encode(text)`
- Returns the embedding as a Python `list` (converted from NumPy array)
- Used by both the chunking pipeline and the query pipeline

The model is loaded **once at module import time** as a global variable — no repeated loading overhead.

---

#### `vector_store.py` — FAISS Vector Store

**Dependencies:** `faiss`, `numpy`, `json`, `os`

**Class:** `VectorStore`

**Constructor `__init__(dimension, index_path, metadata_path)`:**
- If `vector_index.faiss` exists on disk → loads it with `faiss.read_index()`
- Otherwise → creates a new `faiss.IndexFlatL2(384)` (L2 distance / Euclidean search)
- If `vector_metadata.json` exists → loads it as a Python list
- Otherwise → starts with empty list

**`add(embedding, metadata)`:**
- Converts embedding list to `float32` NumPy array
- Adds to FAISS index via `index.add(vector)`
- Appends metadata dict to `self.metadata` list

**`search(query_embedding, top_k=3)`:**
- Converts query to `float32` NumPy array
- Calls `index.search(vector, top_k)` → returns distances + indices
- For each result: copies metadata, computes **similarity score** as `1 / (1 + L2_distance)`
- Returns list of metadata dicts each with a `score` field (higher = more relevant)

**`save()`:**
- Writes FAISS index to `vector_index.faiss` via `faiss.write_index()`
- Writes metadata list to `vector_metadata.json` as pretty-printed JSON
- Called after every chunk insertion in the upload pipeline

> **Current files on disk:** `vector_index.faiss` (~3.7 MB) and `vector_metadata.json` (~6 MB), meaning the index already has real data from previous PDF uploads.

---

#### `answer_service.py` — LLM Answer Generation + Citation Formatting

**Dependencies:** `subprocess`

**`generate_answer(question, chunks)`:**
1. Builds context string by joining top-K retrieved chunks:
   ```
   (Page 3): <chunk text>
   
   (Page 5): <chunk text>
   ```
2. Constructs a **strict, grounded prompt** sent to Ollama:
   - Role: precise question-answering assistant
   - Rules: answer ONLY from provided context, bullet points only, max 5 bullets
   - Fallback: `"I don't know based on the provided document."` if context doesn't contain the answer
3. Runs `ollama run llama3` as a **subprocess**, passing the prompt via stdin as UTF-8 bytes
4. Captures stdout, decodes as UTF-8 (with error ignore), strips whitespace
5. Returns a formatted final answer string containing both the LLM answer and citations

**`format_sources(chunks)`:**
- Deduplicates chunks by `(source, page_number, section_heading, start_paragraph, end_paragraph)`
- For each unique source, formats a citation line:
  ```
  - filename.pdf | Page 3 | Paragraphs 2–4 | Section: Introduction | Score: 0.8312
  ```
- Returns all citations joined by newlines

---

## 4. Frontend — Detailed Breakdown

**Location:** `frontend/leximind-frontend/`  
**Start command:** `npm run dev` (runs on `http://localhost:5173`)

### 4.1 Tech Stack

| Technology | Version | Role |
|---|---|---|
| React | 19.2.0 | UI framework |
| TypeScript | ~5.9.3 | Type safety |
| Vite | 7.2.4 | Dev server + bundler |
| `@vitejs/plugin-react-swc` | 4.2.2 | Fast React refresh via SWC |
| ESLint | 9.x | Linting |

No routing library. No state management library. No UI component library. Pure React + TypeScript + Vite.

---

### 4.2 API Client

**File:** `src/api/backend.ts`

Typed fetch wrappers communicating with `http://127.0.0.1:8000`:

**`uploadPdf(file: File)`**
- Builds `FormData` with key `"file"`
- `POST /upload/pdf` with `multipart/form-data`
- Throws `Error` on non-OK response
- Returns parsed JSON

**`askQuestion(question: string)`**
- `POST /query` with `Content-Type: application/json`
- Body: `{ question }`
- Throws `Error` on non-OK response
- Returns parsed JSON

---

### 4.3 Components

#### `UploadPdf.tsx`
**State:** `file`, `status` (string message), `loading` (boolean)

- Renders a file `<input accept=".pdf">` and an Upload button
- On file selection: validates MIME type is `application/pdf`, shows error if not
- On upload click:
  - Sets loading state
  - Calls `uploadPdf(file)` from API client
  - Shows success or error message
  - Clears selected file on success
- Button is disabled while loading; shows `"Uploading..."` during in-flight request

#### `AskQuestion.tsx`
**State:** `question`, `answer`, `sources`, `loading`, `error`

- Renders a `<textarea>` for question input and an Ask button
- On Ask click:
  - Clears previous answer/sources/error
  - Calls `askQuestion(question)` from API client
  - Sets `answer` and `sources` state from response
  - Clears question input on success
- Renders a hint message when idle (no answer yet)
- Renders `<AnswerBox>` component only when `answer` is non-empty
- Button disabled while loading or when question is empty

#### `AnswerBox.tsx`
**Props:** `answer: string`, `sources: string`

- Returns `null` if `answer` is empty
- Renders the answer in a styled card with `white-space: pre-wrap` to preserve formatting
- Parses `sources` string by splitting on `\n` and filtering lines starting with `"-"`
- **Note:** The sources `<ul>` rendering block is currently **commented out** — sources are received but not displayed in the UI

---

### 4.4 Pages

#### `Home.tsx`
Simple layout page. Renders:
```tsx
<div style={{ maxWidth: "800px", margin: "40px auto" }}>
  <h1>LexiMind</h1>
  <UploadPdf />
  <hr />
  <AskQuestion />
</div>
```

No routing. Single-page app. The entire UI lives on one screen.

---

## 5. End-to-End Data Flow

### Upload Flow
```
User selects PDF in browser
    → UploadPdf.tsx calls uploadPdf(file)
    → POST /upload/pdf (multipart)
    → upload.py saves file to uploaded_pdfs/
    → pdf_service.extract_text_from_pdf() extracts pages + paragraphs
    → pdf_service.clean_extracted_text() removes headers/footers/URLs/junk
    → chunking_service.chunk_text() produces semantic chunks
        (each paragraph embedded during chunking for similarity comparison)
    → For each chunk:
        → embedding_service.generate_embedding(chunk.text) → 384-dim vector
        → vector_store.add(embedding, metadata)
        → vector_store.save() → writes vector_index.faiss + vector_metadata.json
    → Returns { filename, pages_extracted, total_chunks, message }
    → UploadPdf.tsx shows success status
```

### Query Flow
```
User types question in browser
    → AskQuestion.tsx calls askQuestion(question)
    → POST /query { question }
    → query.py embeds the question via generate_embedding()
    → vector_store.search(query_embedding, top_k=5)
        → FAISS IndexFlatL2 nearest-neighbor search
        → Returns top 5 chunks with L2-derived similarity scores
    → answer_service.generate_answer(question, chunks)
        → Builds grounded prompt with retrieved context
        → subprocess: ollama run llama3 (local LLM inference)
        → Returns answer text
    → answer_service.format_sources(chunks)
        → Deduplicates and formats citation strings
    → Returns { question, answer, sources }
    → AskQuestion.tsx sets answer state
    → AnswerBox.tsx renders the answer
```

---

## 6. Persisted Artifacts on Disk

| File | Size | Description |
|---|---|---|
| `backend/vector_index.faiss` | ~3.7 MB | FAISS binary index with all embedded chunks |
| `backend/vector_metadata.json` | ~6.0 MB | JSON array with text + page + paragraph + section metadata for every stored chunk |
| `backend/uploaded_pdfs/` | Varies | Raw uploaded PDF files |

The vector store survives server restarts. On startup, `VectorStore.__init__()` automatically loads both files from disk if they exist.

---

## 7. What Is NOT Yet Implemented

The following features are **planned** but have zero implementation currently:

| Feature | Status |
|---|---|
| BM25 / keyword search | ❌ Not started |
| Hybrid search (dense + sparse) | ❌ Not started |
| Reranking (CrossEncoder / BGE) | ❌ Not started |
| Context builder / token budgeting | ❌ Not started |
| Streaming responses from Ollama | ❌ Not started |
| Workspaces / multi-user collections | ❌ Not started |
| Notes generation | ❌ Not started |
| Flashcard generation | ❌ Not started |
| Citation navigation (click to page) | ❌ Not started |
| OCR / scanned PDF support | ❌ Not started |
| Image understanding (CLIP, BLIP) | ❌ Not started |
| Audio transcription (Whisper) | ❌ Not started |
| Multi-agent workflows | ❌ Not started |
| Semantic memory / knowledge graph | ❌ Not started |
| Evaluation framework | ❌ Not started |
| SQLite / persistent workspace DB | ❌ Not started |
| Cloud sync / hybrid mode | ❌ Not started |
| PDF.js in-browser viewer | ❌ Not started |
| Zustand / global state management | ❌ Not started |
| Source citation UI (visible to user) | ⚠️ Partially done (commented out in AnswerBox.tsx) |

---

## 8. Current Limitations

1. **Dense-only retrieval** — only semantic (vector) search. No keyword-based BM25 fallback.
2. **No reranking** — top-K results from FAISS are passed directly to the LLM without re-ranking.
3. **Ollama called via subprocess** — blocking call; no streaming; no async.
4. **Global in-memory vector store** — shared across requests via module-level global. Not thread-safe at scale.
5. **Double embedding during chunking** — paragraphs are embedded once during chunking (for similarity) and once during indexing. Redundant computation.
6. **No authentication** — any user can upload and query.
7. **No workspace isolation** — all uploaded PDFs share a single FAISS index.
8. **Source citations not displayed** — the UI code exists but is commented out in `AnswerBox.tsx`.
9. **No error recovery for corrupt PDFs** — `pdfplumber` failures are unhandled.
10. **Single-page UI** — no routing, no library view, no workspace management.
11. **No eval framework** — no way to measure retrieval quality, faithfulness, or citation accuracy.

---

## 9. Development Roadmap (Phases)

| Phase | Name | Priority | Status |
|---|---|---|---|
| **Phase 1** | Production RAG Foundation (BM25, Hybrid Search, Reranking, Streaming) | CRITICAL | 🔴 Not started |
| **Phase 2** | Product V1 (Workspaces, Notes, Flashcards, Better UI, SQLite) | CRITICAL | 🔴 Not started |
| **Phase 3** | Image Intelligence (OCR, PaddleOCR, CLIP, scanned PDFs) | HIGH | 🔴 Not started |
| **Phase 4** | Audio Intelligence (Whisper, lecture/meeting processing) | HIGH | 🔴 Not started |
| **Phase 5** | Unified Multimodal Search (CLIP, ImageBind, cross-modal retrieval) | HIGH | 🔴 Not started |
| **Phase 6** | Agent Workflow System (Planner, Retriever, Verifier agents) | HIGH | 🔴 Not started |
| **Phase 7** | Memory & Knowledge Graph (Neo4j, entity linking) | HIGH | 🔴 Not started |
| **Phase 8** | Evaluation Framework (Recall, Precision, Faithfulness, Citation Accuracy) | MANDATORY | 🔴 Not started |
| **Phase 9** | Hybrid Infrastructure (Qdrant, PostgreSQL, Redis, MinIO, Cloud Sync) | MEDIUM | 🔴 Not started |
| **Phase 10** | Advanced Intelligence (Video, Diagram QA, Autonomous Retrieval) | FUTURE | 🔴 Not started |

---

*LexiMind is a Knowledge Operating System. Retrieval quality is more important than model size. Grounding is more important than fluent answers.*
