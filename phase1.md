# LexiMind — Phase 1: Production Retrieval Layer

> **Status:** ✅ Complete · **Tests:** 35/35 passing · **Scope:** make retrieval reliable
> before any multimodal work begins.
>
> This is the **single canonical reference** for Phase 1. A new engineer should be able to
> read only this file and understand everything that was built, why, and how to extend it.

---

## Table of Contents

1. [Phase 1 Overview](#1-phase-1-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Codebase Audit Findings](#4-codebase-audit-findings)
5. [Metadata System](#5-metadata-system)
6. [BM25 Implementation](#6-bm25-implementation)
7. [Hybrid Retrieval](#7-hybrid-retrieval)
8. [Reciprocal Rank Fusion (RRF)](#8-reciprocal-rank-fusion-rrf)
9. [Reranking Layer](#9-reranking-layer)
10. [Query Analysis Layer](#10-query-analysis-layer)
11. [Evaluation Framework](#11-evaluation-framework)
12. [Testing](#12-testing)
13. [Performance Improvements](#13-performance-improvements)
14. [File Changes Summary](#14-file-changes-summary)
15. [Developer Guide](#15-developer-guide)
16. [Future Connection to Phase 2](#16-future-connection-to-phase-2)
17. [Lessons Learned](#17-lessons-learned)

---

## 1. Phase 1 Overview

### Goal

Build a **production-grade retrieval layer** so that what reaches the LLM is the *right*
context, reliably. Per the project's guiding principle:

> "Retrieval quality is more important than model size. Grounding is more important than
> fluent answers."

A great LLM cannot answer well from bad context. Phase 1 makes the *retrieval* — not the
generation — the thing we trust.

### Why retrieval improvements were necessary

The MVP retrieved with **dense vector search only**. Dense (embedding) search is excellent
at *meaning* but has well-known blind spots:

- **Exact terms** — identifiers, acronyms, numbers, rare names, API symbols. If you search
  `IndexFlatL2` or `errno 13`, an embedding model often "rounds" it to something
  semantically near but lexically wrong.
- **No second opinion** — the top-K from one method went straight to the LLM. Nothing
  re-checked whether those chunks were actually relevant to the *specific* query.
- **No measurement** — there was no way to know if a change made retrieval better or worse.

### Problems with the previous architecture

| Problem | Consequence |
|---|---|
| Dense-only retrieval | Misses exact-match / keyword queries |
| No reranking | Top-K never re-scored against the query; precision left on the table |
| No evaluation | "Improvements" were guesses, not measured |
| Thin metadata | Couldn't filter by document/workspace/topic; weak citations |
| Storage glued to the web layer | Untestable; no way to build the stack in a script/test |
| Two real bugs (see §4) | O(n²) write amplification; corrupted results on small corpora |

### Expected benefits

- **Recall** ↑ via hybrid (dense **+** BM25) — two complementary recall mechanisms.
- **Precision** ↑ via cross-encoder reranking — a precise second pass over candidates.
- **Trust** via an **evaluation framework** — every future change is measurable.
- **Filtering & citations** via **enriched metadata** — per-document/workspace retrieval.
- **Maintainability** via a clean `app/retrieval/` package with one orchestrator.

---

## 2. Previous Architecture

### Original retrieval flow

```
          ┌─────────────────────────── INGESTION ───────────────────────────┐
  PDF ──▶ extract (pdfplumber) ──▶ clean ──▶ chunk ──▶ embed each chunk ──▶ FAISS.add ──▶ save()
                                                                                   ▲
                                                                          (called PER CHUNK)

          ┌──────────────────────────── QUERY ─────────────────────────────┐
  Question ──▶ embed (MiniLM) ──▶ FAISS IndexFlatL2 top-5 ──▶ Ollama (llama3) ──▶ Answer + citations
```

Condensed:

```
Query → Embedding → FAISS → Top-K → LLM
```

### Components (before)
- **Embeddings:** `all-MiniLM-L6-v2`, 384-dim, loaded once at import.
- **Vector store:** FAISS `IndexFlatL2` (exact L2 search) + a parallel
  `vector_metadata.json` list (2,436 chunks already indexed).
- **Chunking:** paragraph-aware; split when `> 250` words or cosine similarity `< 0.75`.
- **LLM:** Ollama `llama3` via `subprocess`.

### Limitations
1. **Dense-only** — see §1.
2. **No rerank** — raw FAISS order fed straight to the LLM.
3. **Score = `1/(1+L2)`** — a monotone transform of distance, not a calibrated relevance.
4. **No filtering** — every query searched the entire shared index.
5. **No evals** — quality was unmeasured.
6. **Coupling & bugs** — storage lived inside the HTTP route; two correctness/perf bugs (§4).

---

## 3. New Architecture

### Final retrieval pipeline

```
                         ┌──────────────────────────────────────────────┐
   Query (text)          │             RetrievalPipeline.run            │
        │                │                                              │
        ▼                │   1. Query Analysis  (type/intent/keywords)  │
   ┌─────────┐           │            │  → fusion weights               │
   │ analyze │───────────┤            ▼                                 │
   └─────────┘           │   2. Embed query (MiniLM, 384-d)             │
                         │            │                                 │
              ┌──────────┴────────────┼─────────────────────┐           │
              ▼                       ▼                     │           │
      ┌───────────────┐      ┌─────────────────┐            │           │
      │ Dense (FAISS) │      │  Sparse (BM25)  │   ← 3. retrieve top-30 each
      │   top-30      │      │     top-30      │            │           │
      └───────┬───────┘      └────────┬────────┘            │           │
              │   (each applies metadata filters)           │           │
              └───────────────┬───────────────────┘         │           │
                              ▼                             │           │
                    ┌───────────────────┐                   │           │
                    │  4. RRF Fusion    │  rank-based, scale-free        │
                    │  (dedup by id)    │  → top-30 candidates           │
                    └─────────┬─────────┘                   │           │
                              ▼                             │           │
                    ┌───────────────────┐                   │           │
                    │ 5. BGE Reranker   │  cross-encoder, (q,chunk) pair │
                    │  top-30 → top-5   │  precise relevance             │
                    └─────────┬─────────┘                   │           │
                              ▼                             │           │
                    ┌───────────────────┐                   │           │
                    │ 6. Context Builder│  numbered [1..n] + page labels │
                    └─────────┬─────────┘                   │           │
                              │                             │           │
                         ─────┴───────────────────────────────────────  │
                              ▼                                          │
                         Ollama (llama3)  ──▶  Answer + citations        │
                         └──────────────────────────────────────────────┘
```

Condensed (the Phase-1 target, achieved):

```
Query
 → Query Analysis
 → Dense Retrieval ─┐
 → BM25 Retrieval ──┤→ RRF Fusion → Reranker → (Metadata Filtering applied in-retrieval) → Final Chunks → LLM
```

### Purpose of each stage

| Stage | Purpose | Code |
|---|---|---|
| **Query Analysis** | Classify the query (question/keyword/definition/…) and derive dense/sparse fusion weights; seam for future filters & multimodal routing | `app/retrieval/query_analysis.py` |
| **Dense Retrieval** | Semantic recall via FAISS embeddings | `app/retrieval/dense_retriever.py` |
| **Sparse Retrieval (BM25)** | Exact-term / keyword recall | `app/retrieval/bm25_retriever.py` |
| **RRF Fusion** | Merge the two ranked lists using ordinal rank (scale-free), dedup by `chunk_id` | `app/retrieval/fusion.py` |
| **Reranking** | Cross-encoder re-scores (query, chunk) pairs → precision | `app/retrieval/reranker.py` |
| **Metadata Filtering** | Restrict to a document/workspace/source/topic | `app/retrieval/filters.py` + `schemas.py` |
| **Context Builder** | Assemble a numbered, page-labeled context block | `app/retrieval/pipeline.py` |
| **Orchestrator** | Wire all stages behind one `run()` entry point | `app/retrieval/pipeline.py` |

---

## 4. Codebase Audit Findings

### Existing features discovered
- Working dense RAG (extract → clean → chunk → embed → FAISS → top-5 → Ollama).
- Decent **semantic chunking** (paragraph-aware, similarity-based splits).
- Heuristic **PDF cleaning** (repeated header/footer removal, URL/short-junk filtering).
- 2,436 chunks already indexed (96% from `OS-Book.pdf`).

### Two real bugs found (and fixed)
1. **Write amplification:** `vector_store.save()` was **inside the per-chunk loop** in
   `upload.py` — the FAISS index *and* the ~6 MB JSON were rewritten on **every chunk** of
   **every upload** (O(n²) disk I/O). → Fixed: ingest now saves **once per document**.
2. **FAISS padding leak (correctness):** `VectorStore.search` used `if idx < len(metadata)`.
   When `top_k > number of vectors`, FAISS pads results with `-1`; since `-1 < len`, the
   sentinel passed the check and aliased to `metadata[-1]`, injecting the last chunk
   repeatedly. This corrupted results (and was caught by the integration test, not by eye).
   → Fixed:

   ```python
   # app/services/vector_store.py
   if 0 <= idx < len(self.metadata):   # was: if idx < len(self.metadata)
   ```

### Refactoring performed
- **Config centralized** → `app/core/config.py` (`Settings`, env-overridable, offline defaults).
- **Singletons decoupled from HTTP** → `app/core/state.py` (vector store, retrievers,
  pipeline). Previously the global `VectorStore` lived *inside* `api/upload.py` and `query.py`
  imported it from there — impossible to construct for tests/scripts.
- **Ingestion extracted** → `app/services/ingestion_service.py` (one tested path; batch
  embedding; save-once).
- Routes reduced to thin transport adapters.

### Technical debt removed
- Hard-coded paths/model names scattered across modules → all in `Settings`.
- Per-chunk save → per-document save.
- Padding-leak bug → fixed.
- Leftover `"Bookture API"` string in the health route → `"LexiMind API"`.
- `requirements.txt` was UTF-16 / space-mangled → regenerated as clean UTF-8.

### Architecture changes
- New `app/retrieval/` package (8 modules) with a single orchestrator.
- New `app/eval/` package for measurement.
- New `scripts/` for migration and evaluation.

---

## 5. Metadata System

### Schema

Every **newly ingested** chunk now carries this record (stored in `vector_metadata.json`,
parallel to the FAISS vector at the same index position):

```json
{
  "chunk_id": "doc_24d3f5459e64:5",
  "document_id": "doc_24d3f5459e64",
  "source": "OS-Book.pdf",
  "filename": "OS-Book.pdf",
  "page_number": 12,
  "section": "Process Scheduling",
  "section_heading": "Process Scheduling",
  "topic": "Process Scheduling",
  "created_at": "2026-06-04T17:03:27.922246+00:00",
  "chunk_index": 5,
  "start_paragraph": 2,
  "end_paragraph": 4,
  "text": "…chunk text…"
}
```

- `document_id` / `chunk_id` are **stable & deterministic** — derived from the filename so
  legacy records and re-ingests of the same file collapse to the same ids:

  ```python
  # app/retrieval/schemas.py
  def derive_document_id(source: str) -> str:
      return "doc_" + hashlib.sha1((source or "unknown").encode()).hexdigest()[:12]

  def derive_chunk_id(source: str, chunk_index) -> str:
      return f"{derive_document_id(source)}:{chunk_index}"
  ```

- `section_heading` is kept as a **legacy alias** of `section` so the existing
  `answer_service.format_sources` keeps working unchanged.
- `topic` is currently the nearest section heading (a lightweight, swappable default).

### Why metadata matters
- **Filtering** — "search only this document / workspace / topic."
- **Citations** — page + section + paragraph range make grounded, clickable sources.
- **Dedup & fusion** — `chunk_id` is the key RRF uses to merge duplicates.
- **Evaluation** — ground truth references `chunk_id` / `source`.

### Filtering strategy
Filters are declarative (`RetrievalFilter`) and applied **inside** each retriever (with
over-fetch, because FAISS/BM25 have no native server-side filter):

```python
# app/retrieval/schemas.py  (OR within a field, AND across fields)
RetrievalFilter(source="OS-Book.pdf", topic=["scheduling", "memory"])
```

Single value or list per field; unknown request keys are ignored (forward-compatible).

### Migration of legacy data
The 2,436 pre-Phase-1 records (which only had
`chunk_index, page_number, section_heading, source, start/end_paragraph, text`) were
**backfilled** by `scripts/migrate_metadata.py` — idempotent, timestamped `.bak` backup,
**FAISS vectors untouched** (only JSON keys added). Verified: all 2,436 now have the full
schema.

### Future multimodal compatibility
The schema and `RetrievalFilter` are designed to grow without breaking call sites: future
facets like `modality` (text/image/audio), `language`, or date ranges slot into the same
dict + filter. `QueryAnalysis.wants_modalities` already exists as the routing seam.

---

## 6. BM25 Implementation

### What BM25 is
BM25 (Best Matching 25) is the classic **sparse, lexical** ranking function. It scores a
document for a query from term frequency (how often query terms appear), inverse document
frequency (how rare/informative those terms are), and a length normalization. It matches
**words**, not meaning.

### Why it was added
Dense embeddings miss exact lexical matches; BM25 nails them. Fusing both (hybrid) is
consistently stronger than either alone — they fail in different places.

### Exact-matching benefits
Queries that BM25 rescues: rare identifiers, acronyms, numbers, proper nouns, code symbols
(`IndexFlatL2`, `errno 13`, `BM25 k1=1.2`). The tokenizer deliberately keeps numbers:

```python
# app/retrieval/bm25_retriever.py
_TOKEN_RE = re.compile(r"[a-z0-9]+")
def tokenize(text): return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]
```

### Design decisions
- **Single source of truth:** the corpus *is* the VectorStore's metadata list, so dense and
  sparse views can never drift apart.
- **Lazy rebuild:** `rank-bm25`'s `BM25Okapi` has no incremental API; on corpus change we
  `mark_dirty()` and the next `retrieve()` rebuilds. Cheap at LexiMind's human-paced ingest,
  and avoids the bug surface of a hand-rolled incremental index.
- **Offline tokenizer:** inline stopword set (no `nltk` download).

```python
class BM25Retriever:
    def build(self): ...            # (re)build from current corpus
    def mark_dirty(self): ...       # next retrieve() rebuilds
    def add_documents(self, n=1): ..# ingestion hook (marks dirty)
    def retrieve(self, query, top_k, *, filters=None) -> list[RetrievedChunk]: ...
```

### Files
- **Created:** `app/retrieval/bm25_retriever.py`
- **Modified:** `app/services/ingestion_service.py` (calls `add_documents` after indexing);
  `app/core/state.py` (constructs the singleton).

---

## 7. Hybrid Retrieval

### Dense retrieval
Semantic search: embed the query, find nearest chunk vectors in FAISS. Great at meaning,
weak at exact tokens. Wrapped by `DenseRetriever` so it returns the same `RetrievedChunk`
shape as BM25.

### Sparse retrieval
BM25 (§6): exact lexical matching. Great at tokens, blind to synonyms/paraphrase.

### Why hybrid is superior
They are **complementary**. A query like *"how does the OS avoid two processes entering the
critical section?"* benefits from dense (paraphrase of "mutual exclusion") **and** BM25
(exact "critical section"). Fusing both lists recovers documents either method alone would
miss.

### Retrieval flow

```
                 query text ──────────────┐
   query embedding ──┐                     │
                     ▼                     ▼
              ┌──────────────┐      ┌──────────────┐
              │ DenseRetr.   │      │ BM25Retr.    │
              │  top-30      │      │  top-30      │
              └──────┬───────┘      └──────┬───────┘
                     │  filters applied per retriever │
                     └───────────┬────────────────────┘
                                 ▼
                          ┌─────────────┐
                          │   RRF (§8)  │  weights from Query Analysis
                          └──────┬──────┘
                                 ▼
                       fused candidates (top-30)
```

`HybridRetriever` stays a pure **candidate generator** — reranking & context building live
downstream in the pipeline, which keeps it trivially testable with a fake `DenseRetriever`.

---

## 8. Reciprocal Rank Fusion (RRF)

### Why RRF was selected
Dense similarity and BM25 scores live on **incomparable scales**. Normalizing them
(min-max, z-score) is brittle and dataset-dependent. RRF ignores raw scores and uses only
**ordinal rank**, which is always comparable across retrievers — robust and parameter-light.

### How fusion works

```
RRF(d) = Σ_r  weight_r · 1 / (k + rank_r(d))
```

- `rank_r(d)` = d's 1-based position in retriever r's list.
- `k` = smoothing constant (default **60**, per Cormack et al. 2009) that damps very-high
  ranks so no single list dominates.
- Documents are merged by `chunk_id`; the fused score sums each list's contribution.

```python
# app/retrieval/fusion.py (core)
for list_idx, ranked in enumerate(ranked_lists):
    weight = weights[list_idx]
    for position, chunk in enumerate(ranked, start=1):     # 1-based rank
        fused_score[chunk.chunk_id] += weight * (1.0 / (k + position))
```

### Worked example (k=60)
Dense order: `[A, B, C]` · Sparse order: `[B, A, D]`

| doc | dense term | sparse term | fused | rank |
|---|---|---|---|---|
| A | 1/61 | 1/62 | **0.0325** | 1 (tie) |
| B | 1/62 | 1/61 | **0.0325** | 1 (tie) |
| C | 1/63 | — | 0.0159 | 3 |
| D | — | 1/63 | 0.0159 | 3 |

A and B (top in *both* lists) rise above C and D (top in only one). A doc that ranks #1 in
both lists beats any doc that ranks #1 in only one.

### Advantages over naive merging
- No score normalization needed (scale-free).
- A doc found by **both** retrievers is rewarded (it appears in two sums).
- Configurable `k`, per-list `weights` (set by query analysis), and `top_k` depth.
- Pure function → fully unit-tested (6 tests).

---

## 9. Reranking Layer

### Why reranking is needed
Dense and BM25 are **bi-encoders / bag-of-words**: they score the query and the chunk
*independently*, then compare. They never read them *together*. A **cross-encoder** feeds
`(query, chunk)` into one transformer and models term interaction directly — far more
precise, but too expensive to run over the whole corpus.

The standard recipe (implemented here): cheap retrieval produces ~30 candidates → the
cross-encoder reorders them → keep the top 5. This is the **highest-leverage precision win**
in the pipeline.

### BGE reranker architecture
`BAAI/bge-reranker-base` is a BERT-style cross-encoder. Input: a `(query, passage)` pair.
Output: a single relevance score. Loaded via `sentence_transformers.CrossEncoder`.

Validated on real data: for *"What are the prerequisites for learning AI?"* it scored the
relevant chunk **0.999** vs **~0.001** for distractors.

### Candidate selection process

```
Hybrid top-30  ──▶  RerankerService.rerank(query, candidates, top_k=5)  ──▶  top-5
                         │
                         ├─ lazy model load (only on first use)
                         ├─ batch all cache-miss pairs into ONE predict() call
                         └─ bounded LRU cache keyed on (query, chunk_id)
```

```python
# app/retrieval/reranker.py (essence)
misses = [i for i,c in enumerate(candidates) if self._cache_get((query,c.chunk_id)) is None]
predicted = self._load().predict([(query, candidates[i].text) for i in misses], batch_size=32)
# fill cache, attach scores, sort desc, take top_k
```

### Performance tradeoffs
- **Cost:** a cross-encoder pass over 30 candidates adds **~1.5 s** (CPU, offline) per query.
- **Mitigations:** lazy load (no cost until used), batching (one model call), LRU cache
  (repeat/paginated queries are free), and a global **`LEXIMIND_ENABLE_RERANKER`** toggle so
  CI / low-latency modes can skip it. First use downloads ~1 GB.

---

## 10. Query Analysis Layer

### Query understanding process
`analyze_query()` is **rule-based and lightweight** (no LLM call → fast, offline). It produces:

```python
@dataclass
class QueryAnalysis:
    raw, normalized, query_type, intent: str
    keywords: list[str]
    is_keyword_heavy: bool
    suggested_filters: RetrievalFilter | None   # future seam
    wants_modalities: list[str]                  # future seam (["text"] for now)
```

- **query_type** ∈ {question, keyword, definition, comparison, summary}.
- **keywords** = content tokens (stopwords removed).
- **is_keyword_heavy** = ≥80% of tokens are content words → exact matching will pay off.

### Metadata-aware retrieval strategy
Analysis drives **fusion weights** so the pipeline adapts per query:

```python
def dense_sparse_weights(self):
    if self.query_type in ("definition","keyword") or self.is_keyword_heavy:
        return (1.0, 1.3)     # lean on BM25
    if self.query_type in ("question","summary"):
        return (1.3, 1.0)     # lean on dense
    return (1.0, 1.0)
```

Weights are intentionally mild — neither retriever is silenced; RRF always sees both lists.

### Future expansion plans
The dataclass already carries `suggested_filters` and `wants_modalities` so later phases can
populate them (extract a document/topic filter from the query, route to image/audio
retrievers) **without changing the pipeline's call site**.

---

## 11. Evaluation Framework

Per the project charter, **evals are mandatory** ("Evals are required before claiming
improvements"). `app/eval/` makes retrieval quality measurable.

### Metrics
| Metric | Meaning |
|---|---|
| **Recall@K** | Of the relevant items, how many appear in the top-K? (For source-level ground truth this becomes *success@K* — was the right document found?) |
| **Precision@K** | Of the top-K returned, what fraction are relevant? |
| **MRR** | Mean Reciprocal Rank — `1/rank` of the *first* relevant hit, averaged over queries. Rewards putting a relevant chunk at position 1. |
| **Latency** | mean / p50 / p95 wall-clock per query |

### How it works
`RetrievalEvaluator.evaluate(retrieve_fn)` accepts **any** `query → List[RetrievedChunk]`
function, so the same harness scores the baseline, hybrid, or full pipeline. Ground truth is
chunk-level (`relevant_chunk_ids`) and/or source-level (`relevant_sources`).

```json
// eval_data/sample_ground_truth.json
[
  {"query": "How does the operating system schedule processes?", "relevant_sources": ["OS-Book.pdf"]},
  {"query": "How do Java generics and the collections framework work?", "relevant_sources": ["javabook 2.pdf"]}
]
```

### Running evaluations

```bash
cd backend
# baseline (dense-only) vs hybrid:
./venv/bin/python -m scripts.run_eval
# add the full pipeline with BGE reranking:
LEXIMIND_ENABLE_RERANKER=1 ./venv/bin/python -m scripts.run_eval --rerank
# custom dataset / output:
./venv/bin/python -m scripts.run_eval --dataset eval_data/sample_ground_truth.json --out eval_data/report.md
```

A markdown report (per-config tables + a comparison table) is written to `eval_data/report.md`.

---

## 12. Testing

`backend/tests/` — **35 tests, all passing.**

| File | Covers |
|---|---|
| `test_fusion.py` | RRF ordering, dedup, weights, `top_k`, input validation (6) |
| `test_bm25.py` | tokenizer, lexical ranking, empty corpus, lazy rebuild, filters (6) |
| `test_hybrid.py` | dense+BM25 merge, shared-candidate promotion (2) |
| `test_reranker.py` | sort, `top_k`, single-batch, cache hits, empty (5) — *fake* cross-encoder, no download |
| `test_filters.py` | match/apply, OR-in-field, AND-across-fields, `build_filter` validation (6) |
| `test_query_analysis.py` | classification, weights, keyword density, stopwords (5) |
| `test_eval.py` | recall/precision/MRR math, source-level GT, markdown (5) |
| `test_integration.py` | **end-to-end**: real FAISS + fake embeddings → analysis → dense+BM25 → RRF → context; + metadata-filter path (2) |

### Commands

```bash
cd backend
./venv/bin/python -m pytest tests/ -q          # full suite (~0.5s)
./venv/bin/python -m pytest tests/test_fusion.py -q
```

### Coverage notes
The integration test exercises the real pipeline without any model download (deterministic
4-dim fake embeddings, reranker disabled). The reranker's batching/caching/sorting logic is
covered with a fake cross-encoder; the *real* `BAAI/bge-reranker-base` was additionally
validated manually on real data (§9).

---

## 13. Performance Improvements

### Before

**Architecture:** `Query → Embedding → FAISS → Top-5 → LLM` (dense-only, no rerank, no eval).

**Metrics:** none — quality was unmeasured. Known issues: O(n²) ingest writes, padding-leak
bug, no exact-match recall.

### After

**Architecture:** `Query → Analysis → (Dense + BM25) → RRF → Rerank → Context → LLM`, with
metadata filtering and a measurement harness.

**Metrics** — `scripts/run_eval --rerank` on the 10-query sample set:

| Config | Recall@5 | Precision@5 | MRR | Mean latency (ms) |
|--------|----------|-------------|-----|-------------------|
| Baseline (dense-only) | 1.000 | 1.000 | 1.000 | ~72 |
| Hybrid (dense+BM25+RRF) | 1.000 | 0.800 | 0.950 | ~21 |
| Full (hybrid+rerank) | 1.000 | 0.820 | 0.950 | ~1564 |

### Honest interpretation (important — this is **not** a claimed win)
- The current corpus is **96% a single document** (`OS-Book.pdf`, 2,349/2,436 chunks) and
  the ground truth is **source-level**, so dense-only **trivially** returns the right
  document — there is almost no headroom for hybrid/rerank to show value here.
- Hybrid's lower precision is BM25 surfacing some off-source lexical matches, counted as
  misses on this imbalanced set; rerank recovers a little (0.80→0.82).
- Latency numbers are **indicative, not rigorous**: the first config measured pays model
  warmup, which is why hybrid looks "faster" than baseline. Reranking's ~1.5 s is the real,
  expected cross-encoder cost over 30 candidates.

**Conclusion:** the pipeline and framework are **correct and wired**; quantifying the
hybrid/rerank quality gain requires a **larger, chunk-level, multi-document** ground-truth
set — that dataset is the next eval task, and the infrastructure to measure it now exists.
A genuine bug fix (padding leak) *did* improve correctness, and the O(n²) ingest write was
eliminated.

---

## 14. File Changes Summary

### New files
| File | Purpose |
|---|---|
| `backend/app/core/config.py` | Central `Settings` (paths, models, retrieval knobs), env-overridable |
| `backend/app/core/state.py` | Process-wide singletons (vector store, retrievers, pipeline) |
| `backend/app/retrieval/__init__.py` | Package surface + pipeline docstring |
| `backend/app/retrieval/schemas.py` | `RetrievedChunk`, `RetrievalFilter`, id derivation |
| `backend/app/retrieval/dense_retriever.py` | FAISS adapter → uniform results |
| `backend/app/retrieval/bm25_retriever.py` | **`BM25Retriever`** (sparse) |
| `backend/app/retrieval/fusion.py` | **RRF** fusion (pure function) |
| `backend/app/retrieval/hybrid_retriever.py` | **`HybridRetriever`** (dense+sparse→RRF) |
| `backend/app/retrieval/reranker.py` | **`RerankerService`** (BGE cross-encoder) |
| `backend/app/retrieval/query_analysis.py` | `analyze_query` + fusion weights |
| `backend/app/retrieval/filters.py` | request-dict → validated `RetrievalFilter` |
| `backend/app/retrieval/pipeline.py` | `RetrievalPipeline` orchestrator + context builder |
| `backend/app/services/ingestion_service.py` | extract→chunk→enrich→batch-embed→index (save once) |
| `backend/app/eval/__init__.py`, `framework.py` | evaluation metrics + dataset loader + reports |
| `backend/scripts/migrate_metadata.py` | backfill enriched metadata onto legacy records |
| `backend/scripts/run_eval.py` | baseline vs hybrid vs full comparison report |
| `backend/eval_data/sample_ground_truth.json` | sample ground-truth dataset |
| `backend/tests/*.py` (8 files) + `backend/conftest.py` | unit + integration tests |
| `phase1.md` | this document |

### Modified files
| File | Change |
|---|---|
| `backend/app/services/vector_store.py` | **Fixed `-1` padding leak** (`0 <= idx < len`); added `size()` |
| `backend/app/services/embedding_service.py` | model name from `Settings`; added batch `generate_embeddings()` |
| `backend/app/api/upload.py` | thin route → delegates to `ingestion_service`; uses shared state |
| `backend/app/api/query.py` | runs full `RetrievalPipeline`; accepts `filters`/`top_k`; returns analysis + timings |
| `backend/app/api/health.py` | `"Bookture API"` → `"LexiMind API"` |
| `backend/requirements.txt` | regenerated clean UTF-8; adds `rank-bm25`, `pytest` |
| `backend/vector_metadata.json` | migrated in place (enriched; timestamped `.bak` kept) |

---

## 15. Developer Guide

### Add a new retriever
1. Create `app/retrieval/my_retriever.py` with a `retrieve(...) -> list[RetrievedChunk]`
   method (return `RetrievedChunk.from_metadata(...)` with `rank` set).
2. To fuse it, pass its output list as another argument to
   `reciprocal_rank_fusion([dense, sparse, mine], k=..., weights=[...])`.
3. Construct it in `app/core/state.py` and wire it into `HybridRetriever`/`RetrievalPipeline`.

```python
class MyRetriever:
    def retrieve(self, query, top_k, *, filters=None) -> list[RetrievedChunk]:
        ...  # produce RetrievedChunk objects, set .rank (1-based)
```

### Add a new reranker
Implement the same surface as `RerankerService`:
```python
class MyReranker:
    def rerank(self, query, candidates, *, top_k=None, batch_size=32) -> list[RetrievedChunk]: ...
```
Swap it in `app/core/state.py` (`reranker = MyReranker(...)`). The pipeline only depends on
the `.rerank()` signature.

### Add a metadata field
1. Add the key in `app/services/ingestion_service.py::build_chunk_metadata`.
2. If it should be filterable: add it to `RetrievalFilter` (field + `matches()`) and to
   `_ALLOWED_FIELDS` in `filters.py`.
3. Backfill existing records by extending `scripts/migrate_metadata.py`.
4. Add an accessor `@property` on `RetrievedChunk` if it's read often.

### Extend retrieval logic
- **Tune knobs** via env vars (no code change): `LEXIMIND_DENSE_TOP_K`,
  `LEXIMIND_SPARSE_TOP_K`, `LEXIMIND_RRF_K`, `LEXIMIND_RERANK_CANDIDATES`,
  `LEXIMIND_FINAL_TOP_K`, `LEXIMIND_ENABLE_RERANKER`.
- **Change pipeline stages** in `app/retrieval/pipeline.py::RetrievalPipeline.run`.
- **Always** add/adjust a test in `backend/tests/` and re-run the eval to confirm no regression.

---

## 16. Future Connection to Phase 2

Phase 1 was built so later phases plug in **without rework**:

```
                         ┌──────────────────────────────────────┐
   Phase 1 (done):       │  RetrievalPipeline.run(query, ...)    │
                         │   → RetrievalResult{chunks, context,  │
                         │      analysis, timings}               │
                         └───────────────┬──────────────────────┘
                                         │  stable contract
        ┌────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                  ▼
 Context Engineering Engine        Agents (Phase 6)                  Knowledge Graph (Phase 7)
 - replace build_context with      - Planner/Retriever/Verifier      - entities from chunk.metadata
   token budgeter + compressor       call pipeline.run as a TOOL     - graph as another retriever
   (the seam already exists in        and read RetrievalResult         fused via RRF
   pipeline.build_context)            (analysis = routing signal)
                                         │
                                         ▼
                              Multimodal Retrieval (Phase 3–5)
                              - image/audio retrievers return RetrievedChunk
                              - QueryAnalysis.wants_modalities routes
                              - fuse all modalities with the SAME RRF
```

| Phase 2 capability | Phase 1 dependency it builds on |
|---|---|
| **Context Engineering** | `build_context` is the single seam to swap in token budgeting / dedup / compression |
| **Multimodal Retrieval** | uniform `RetrievedChunk` + `RetrievalFilter(modality)` + `wants_modalities`; new modalities fuse via the same RRF |
| **Agents** | `RetrievalPipeline.run` is a clean tool boundary; `QueryAnalysis` gives agents routing signals |
| **Knowledge Graph** | stable `document_id`/`chunk_id` + metadata are the anchors for entity/concept links; a graph retriever fuses like any other list |
| **Workspaces** | `RetrievalFilter(workspace=...)` is already wired end-to-end |
| **Measurement** | the eval framework gates every future change |

---

## 17. Lessons Learned

### Architectural decisions
- **Rank-based fusion (RRF) over score normalization** — robust, parameter-light, and the
  pure-function design made it the most-tested component.
- **Uniform `RetrievedChunk` contract** — letting every retriever (and future modality)
  return one shape is what makes hybrid fusion, filtering, and reranking compose cleanly.
- **Lazy model loading + config toggles** — keeps imports/tests fast and offline; heavy
  models (reranker) only load when actually used.
- **Single source of truth for the corpus** — BM25 reads the vector store's metadata, so
  dense and sparse can never drift.

### Tradeoffs
- **BM25 full rebuild** vs. incremental — chose simplicity/correctness over micro-perf;
  fine at current ingest rate.
- **Reranker latency (~1.5 s)** vs. precision — gated behind a flag so the cost is opt-in.
- **FAISS `IndexFlatL2`** kept (exact, simple) rather than switching index types — correct at
  this scale; avoids invalidating the existing index.

### Known limitations
- FAISS is exact flat L2 (revisit IVF/HNSW + cosine normalization for large corpora).
- Reranking adds latency and a ~1 GB first-use download.
- The sample eval set is small and source-imbalanced → can't yet *prove* a hybrid/rerank
  quality gain (§13).
- Embeddings still computed twice (chunking-time similarity + index-time) — a known
  ingestion inefficiency carried over from the MVP.

### Future improvements
1. **Build a larger chunk-level, multi-document ground-truth set** — the single most
   valuable next step; turns "the pipeline runs" into "the pipeline is *better*, measured."
2. Cosine-normalized embeddings (better fit for MiniLM than L2).
3. Token-budgeting context builder (Phase 2 seam).
4. Streaming Ollama responses.
5. Eliminate double embedding during ingestion.
6. Per-workspace indexes once multi-tenant usage arrives.
```
