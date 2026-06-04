# LexiMind — Phase 2: Context Engineering Engine

> **Status:** ✅ Complete · **Tests:** 65/65 passing (24 new Phase-2 tests) · **Builds on:** [phase1.md](./phase1.md)
>
> The official reference for Phase 2. A new engineer should understand the entire context
> engineering implementation from this file alone.
>
> **One-line goal:** deliver the *maximum useful information* to the LLM using the *minimum
> number of tokens* — without ever losing a citation.

---

## Table of Contents
1. [Phase 2 Overview](#1-phase-2-overview)
2. [Previous Architecture](#2-previous-architecture)
3. [New Architecture](#3-new-architecture)
4. [Audit Findings](#4-audit-findings)
5. [Context Builder Service](#5-context-builder-service)
6. [Duplicate Detection](#6-duplicate-detection)
7. [Evidence Ranking](#7-evidence-ranking)
8. [Token Budget Management](#8-token-budget-management)
9. [Context Compression](#9-context-compression)
10. [Citation Preservation](#10-citation-preservation)
11. [Context Assembly](#11-context-assembly)
12. [Evaluation Framework](#12-evaluation-framework)
13. [Testing](#13-testing)
14. [Performance Improvements](#14-performance-improvements)
15. [File Changes Summary](#15-file-changes-summary)
16. [Developer Guide](#16-developer-guide)
17. [Connection to Future Phases](#17-connection-to-future-phases)
18. [Lessons Learned](#18-lessons-learned)

---

## 1. Phase 2 Overview

### Goals
Insert a **context engineering engine** between retrieval and the LLM that:
- removes duplicate / near-duplicate evidence,
- ranks evidence by how much it actually helps answer the query,
- enforces a **token budget** so the prompt never overflows the model window,
- compresses redundancy while preserving information,
- assembles a clean, citation-bearing context block for the LLM.

### Motivation
Phase 1 made *retrieval* reliable. But retrieving the right chunks is only half the job —
**what you put in the prompt, and how, determines the answer.** Garbage-in still means
garbage-out, even with perfect retrieval.

### Why retrieval alone is insufficient
| Problem with "retrieve → LLM" | Effect |
|---|---|
| Hybrid retrieval surfaces the same passage twice (dense **and** BM25) | wasted tokens, skewed model attention |
| No token accounting | risk of silently overflowing the context window |
| Top-K dumped in raw rerank order | no document grouping, no logical flow |
| Citations deduped only for *display* | provenance could be dropped before the LLM sees it |
| Long chunks included whole | low-value sentences crowd out high-value ones |

### Context engineering philosophy
> **Maximize signal per token.**

Every token in the prompt should earn its place. The engine treats the context window as a
*scarce budget* and spends it on the densest, most relevant, non-redundant, attributable
evidence — in that priority order. This is the foundation for **token optimization** and the
future **verification agent** (both rely on a clean, measured context).

---

## 2. Previous Architecture

```
   result.chunks (List[RetrievedChunk])
        │
        ▼
   answer_service.generate_answer(question, chunks)
        │   builds context = "\n\n".join("(Page X): text")   ← naive, no [n] markers
        ▼
   Ollama (llama3)  →  answer
```

Condensed: **Retrieved Chunks → LLM.**

### Limitations
1. **Two conflicting context builders.** `pipeline.build_context()` produced a numbered
   `[n]` context into `result.context` — but it was **discarded**; `query.py` instead fed
   raw chunk dicts to `answer_service`, which rebuilt a *different* context. The citation
   markers never reached the LLM.
2. **No token budget.** Nothing measured or capped context size → possible overflow.
3. **No text deduplication.** Duplicate chunk *text* went to the model (only citations were
   deduped, and only for display).
4. **No ranking/compression** beyond raw rerank order.
5. **Citations not guaranteed** to survive into the prompt.

---

## 3. New Architecture

```
   result.chunks (List[RetrievedChunk])  ── from Phase-1 retrieval pipeline
              │
              ▼   ContextBuilderService.build(query, chunks, query_keywords)
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  Duplicate Detection      remove exact / near / structural duplicates       │
   │           ▼                                                                 │
   │  Evidence Ranking         blended score: retrieval + metadata + citation    │
   │           ▼                                                                 │
   │  Token Budget Management   window − system − user − response = available     │
   │           ▼                                                                 │
   │  Context Compression       merge overlaps · remove redundancy · summarize    │
   │           ▼                                                                 │
   │  Context Assembly          group by doc · order · emit [n] + citation        │
   └──────────────────────────────┬─────────────────────────────────────────────┘
                                   ▼
            ContextResult { context, evidence, citations, metrics }
                                   ▼
            answer_service.generate_answer(question, context) → Ollama → answer
```

### Each stage
| Stage | Purpose | Module |
|---|---|---|
| **Duplicate Detection** | Drop repeated/overlapping evidence, keep the best version | `dedup.py` |
| **Evidence Ranking** | Order by *usefulness to this query*, not just model score | `ranking.py` |
| **Token Budget Management** | Carve the window into reserves; never overflow | `budget.py` + `tokenizer.py` |
| **Context Compression** | Reduce tokens while preserving information | `compression.py` |
| **Context Assembly** | Organize into an LLM-friendly, citable block | `assembly.py` |
| **Orchestrator** | Run the stages, return result + metrics | `builder.py` |

> **Implementation note (not silent):** the engine runs **Ranking before Duplicate
> Detection** internally, because dedup must keep the *highest-quality* version of a
> duplicate pair and therefore needs the evidence score first. The conceptual stages are
> exactly as listed above; only the internal ordering of the first two is swapped, and this
> is documented in `builder.py`.

---

## 4. Audit Findings

### Existing implementation (pre-Phase-2)
- Retrieval returned `List[RetrievedChunk]` (rerank-ordered, full metadata, `score`).
- `pipeline.build_context()` existed but its output was unused.
- `answer_service.generate_answer(question, chunks)` built its own naive context **and**
  embedded citations into the answer string.
- `format_sources()` deduped citations for display only.

### Weaknesses
| Area | Weakness |
|---|---|
| Context | duplicate builders; the one feeding the LLM had no `[n]` markers |
| Tokens | zero accounting; unbounded; ~1,600 tokens typical, no cap |
| Dedup | text duplicates reached the LLM |
| Ranking | rerank order only |
| Citations | could be lost between retrieval and prompt |

### Refactoring decisions
1. **One builder.** Remove the duplicate-builder conflict: the new engine's assembler is the
   single source of LLM context; `answer_service` now *consumes* an engineered string.
2. **Wrap, don't mutate.** Introduce an `Evidence` working type so context stages can
   annotate items without polluting the retrieval `RetrievedChunk` contract.
3. **Separate package.** `app/context/` with one module per stage → testable in isolation.
4. **Config-driven.** All knobs (window, reserves, dedup threshold, compression toggle) in
   `Settings`, env-overridable.

---

## 5. Context Builder Service

### Responsibilities
`ContextBuilderService` (`app/context/builder.py`) is the **single entry point**. It:
- converts `RetrievedChunk`s into `Evidence`,
- runs ranking → dedup → compression → budgeting → assembly,
- computes quality metrics,
- returns a `ContextResult{context, evidence, citations, metrics}`.

### Workflow

```
build(query, chunks, query_keywords)
  │
  ├─ Evidence.from_chunk(c) for each chunk      (carry text + citations + scores)
  ├─ EvidenceRanker.rank(...)                   → evidence_score, sorted best-first
  ├─ DuplicateChunkDetector.detect(...)         → keep strongest, drop dups
  ├─ if compression:
  │     ContextCompressor.merge_overlapping(...) → fuse same-doc/page, union citations
  │     ContextCompressor.remove_redundancy(...) → drop repeated sentences
  ├─ TokenBudgetManager.plan(user_prompt)        → available_context budget
  ├─ TokenBudgetManager.greedy_fit(..., cost_fn=block_cost)   → kept / dropped
  ├─ if compression: compress_to_fit(dropped[i]) → rescue marginal chunk into leftover
  ├─ ContextAssembler.assemble(kept)             → context string + citations
  └─ compute_metrics(...)                        → ContextResult
```

### Architecture diagram

```
                       ┌─────────────── ContextBuilderService ───────────────┐
   chunks ────────────▶│  EvidenceRanker → DuplicateChunkDetector            │
                       │        → ContextCompressor → TokenBudgetManager      │
                       │        → ContextAssembler → metrics                  │
   query_keywords ────▶│                                                     │
                       └───────────────────────┬─────────────────────────────┘
                                                ▼
                              ContextResult { context, evidence, citations, metrics }
```

Key design point: it budgets on the **rendered block cost** (citation header + text), so the
final assembled context provably fits the window — not just the raw chunk text.

---

## 6. Duplicate Detection

### Why duplicates occur
- **Hybrid retrieval** finds the same passage twice — once via dense, once via BM25.
- **Chunk overlap** — adjacent chunks share sentences; a heading repeats across pages.
- **Re-ingested documents** produce structurally identical chunks.

Duplicates waste the token budget and bias the LLM toward the repeated content.

### Detection strategies (`DuplicateChunkDetector`)
| Strategy | Rule |
|---|---|
| **Exact** | normalized text equality |
| **Near** | Jaccard similarity of word-token sets ≥ threshold (default **0.85**) |
| **Structural** | same `document_id` **and** same page **and** overlapping paragraph ranges |

Detection runs **best-first** (sorted by evidence score), so the survivor of any duplicate
pair is the **highest-quality** version — no information or citation is lost relative to
keeping a worse copy.

### Similarity threshold
```
Jaccard(A, B) = |tokens(A) ∩ tokens(B)| / |tokens(A) ∪ tokens(B)|
```
- `0.85` (default) ≈ "almost the same passage." Lower it to be more aggressive (risk merging
  distinct chunks); raise it to be conservative. Tunable via `LEXIMIND_DEDUP_THRESHOLD`.

### Example
```
A (score 0.9): "operating systems schedule processes and threads efficiently"
B (score 0.5): "operating systems schedule processes and threads"
Jaccard ≈ 6/7 = 0.857 ≥ 0.85  →  B removed, A kept (higher score)
```

---

## 7. Evidence Ranking

### Ranking factors (`EvidenceRanker`)
A transparent, explainable weighted blend of normalized signals:

```
evidence_score = 0.60 · norm(retrieval_score)        # the model's relevance judgment
               + 0.25 · metadata_relevance            # query keywords in section/topic/text
               + 0.15 · citation_confidence           # is it precisely attributable?
```

### Scoring methods
- **`norm(retrieval_score)`** — min-max normalization across the candidate set (equal scores
  map to a neutral 1.0).
- **`metadata_relevance`** — fraction of query keywords appearing in `section`/`topic`
  (weighted 0.6, "aboutness") plus body text (weighted 0.4).
- **`citation_confidence`** — 1.0 for a complete citation (source+doc+page), 0.5 otherwise.

### Prioritization strategy
The resulting `evidence_score` drives **every** downstream decision: which duplicate
survives, which evidence the budget keeps when space runs out, and the assembly order.
Weights are constructor args, so they can be tuned without touching logic.

### Example
Two chunks, equal retrieval score, query = "process scheduling":
```
A: section "Process Scheduling"  → metadata_relevance high  → ranked first
B: section "Unrelated Topic"     → metadata_relevance low   → ranked second
```

---

## 8. Token Budget Management

### Token accounting (`TokenCounter`)
The LLM is Ollama `llama3`, whose exact tokenizer isn't available offline. `TokenCounter`
wraps a **pluggable** count-function; the default heuristic never *under*-estimates (the one
failure that would cause overflow):

```
tokens(text) = max( ceil(chars / 4),        # ~4 chars/token (English rule of thumb)
                    ceil(words · 1.3) )       # sub-word splitting of longer words
```

A precise tokenizer (tiktoken / llama) can be injected later with **zero** call-site changes.

### Context window allocation
```
context_window
  = system_prompt_reserve            (instructions / role)         default 500
  + user_prompt_tokens               (the question, measured)
  + response_reserve                 (room to generate the answer) default 1000
  + available_context_budget         (what's left for evidence)   ← managed here
```

### Budget formula
```
available_context = max(0, context_window − system_reserve − user_prompt_tokens − response_reserve)
```

### Example
```
context_window = 8192, system_reserve = 500, response_reserve = 1000
user prompt "What are the prerequisites for learning AI?" ≈ 9 tokens
available_context = 8192 − 500 − 1000 − 9 = 6683 tokens for retrieved evidence
```
`greedy_fit` then adds evidence (in evidence-score order) until the **rendered** cost
(citation header + text) would exceed 6683; the rest is dropped (or compressed to fit).

---

## 9. Context Compression

### Compression strategies (`ContextCompressor`)
| Strategy | What it does |
|---|---|
| **`merge_overlapping`** | Fuse same-document, same-page evidence into one piece; **union citations**; record `merged_from` lineage |
| **`remove_redundancy`** | Drop sentences already seen in a higher-priority chunk (cross-chunk dedup at sentence granularity) |
| **`compress_to_fit`** | Extractive summary of the *marginal* chunk: keep the sentences most relevant to the query until it fits leftover budget |

### Redundancy removal example
```
A (priority): "Shared sentence here. Unique to A."
B (lower):    "Shared sentence here. Unique to B."
→ A keeps both; B becomes "Unique to B." (shared sentence dropped, B's citation preserved)
```

### Information & citation preservation
- Compression changes **text only** — an evidence's `citations` list is never touched.
- The token counter takes the *max* of two estimates, so compression never under-counts and
  re-introduces overflow.

### Future LLM-based compression (seam)
`compress_to_fit` calls through a `CompressionStrategy` interface:
- default **`ExtractiveStrategy`** (rule-based, deterministic, offline),
- **`LLMCompressionStrategy`** stub — will call a local model for *abstractive* compression;
  currently delegates to extractive so the system stays offline-safe. Swap it in via
  `ContextCompressor(counter, strategy=...)` with no other changes.

---

## 10. Citation Preservation

Citations are a **hard invariant**, not a feature.

### Metadata tracking (`Citation`)
```python
Citation(chunk_id, document_id, source, page_number, section)
Citation.is_complete()  # True only if a reader can be pointed to an exact location
```
Every `Evidence` owns a non-empty `citations: List[Citation]`, built from chunk metadata at
entry (`Citation.from_metadata`).

### Citation flow
```
RetrievedChunk.metadata ──▶ Citation.from_metadata ──▶ Evidence.citations
   merge_overlapping:  union citations (+ merged_from lineage)
   remove_redundancy / compress_to_fit:  text changes, citations untouched
   assemble:  emit inline [n] marker + label; return parallel List[Citation]
```

### Failure prevention
- Dedup keeps the **highest-quality** duplicate (never drops the only good citation).
- Merge **unions** citations rather than overwriting.
- A unit test (`test_merge_preserves_all_citations`) asserts merged evidence still references
  every source `chunk_id`.
- Measured live: **citation coverage = 1.000** across the eval set (§14).

---

## 11. Context Assembly

### Chunk organization (`ContextAssembler`)
1. **Group** evidence by `document_id`.
2. **Order groups** by their best evidence score (strongest context leads).
3. **Order within a document** by page, then paragraph (logical reading flow).
4. **Number** each block `[n]` and attach a citation label; return a parallel citation list.

### Evidence grouping diagram
```
   evidence (mixed)            grouped & ordered              assembled
   ┌───────────────┐          ┌───────────────────┐         [1] OS-Book.pdf · Page 12 · Scheduling
   │ OS p13 (0.7)  │          │ doc OS  (best 0.9) │         <text>
   │ Java p2 (0.4) │   ───▶   │   OS p12 (0.9)     │   ───▶  [2] OS-Book.pdf · Page 13 · Scheduling
   │ OS p12 (0.9)  │          │   OS p13 (0.7)     │         <text>
   └───────────────┘          │ doc Java (0.4)     │         [3] javabook 2.pdf · Page 2
                              │   Java p2 (0.4)    │         <text>
                              └───────────────────┘
```

### Final prompt structure
```
<SYSTEM_PROMPT: grounded QA rules>

Context:
[1] OS-Book.pdf · Page 12 · Process Scheduling
<evidence text>

[2] OS-Book.pdf · Page 13 · Process Scheduling (+ OS-Book.pdf · Page 13)   ← merged block
<merged evidence text>

Question:
<user question>

Answer:
```
The `[n]` markers let the model cite, and the parallel `List[Citation]` lets the API/UI
render sources — both derived from the same assembly pass, so they can't disagree.

---

## 12. Evaluation Framework

### Metrics (`app/context/metrics.py`)
| Metric | Meaning |
|---|---|
| **Context relevance** | mean fraction of query keywords present in kept evidence |
| **Context density** | fraction of context sentences that touch the query (signal-to-noise) |
| **Citation coverage** | fraction of evidence carrying a **complete** citation |
| **Token efficiency** | final context tokens / raw retrieved tokens (lower = leaner) |
| **Compression ratio** | `1 − token_efficiency` (higher = more saved) |
| **Duplicate reduction rate** | fraction of input chunks removed as duplicates |

### Measurement method
`scripts/run_context_eval.py` runs Phase-1 retrieval for each query, then compares:
- **Before:** naive context = raw concatenation of retrieved chunk texts (+ token count).
- **After:** engineered context + the metrics above.

### Benchmark command
```bash
cd backend
LEXIMIND_ENABLE_RERANKER=0 ./venv/bin/python -m scripts.run_context_eval
# → writes eval_data/context_report.md
```

---

## 13. Testing

**65 tests total (24 new for Phase 2), all passing.** Phase-2 tests use a word-count
`TokenCounter` so budgeting is deterministic and **no model/LLM is required.**

| File | Type | Covers |
|---|---|---|
| `test_budget.py` | unit | token counter, reserves, never-negative, greedy fit/overflow (5) |
| `test_dedup.py` | unit | exact / near / structural dup, keep-best, distinct kept (4) |
| `test_ranking.py` | unit | score blend, metadata boost, citation tie-break, empty (4) |
| `test_compression.py` | unit | merge+union citations, redundancy removal, compress-to-fit, noop (6) |
| `test_assembly.py` | unit | numbering, doc grouping, score order, page/¶ order, empty (4) |
| `test_context_metrics.py` | unit | relevance, density, coverage, efficiency/compression (4) |
| `test_context_builder.py` | **integration** | end-to-end engine: dedup+budget+citations, merge preservation, empty, overflow prevention (4) |
| `test_context_helpers.py` | fixture | shared `RetrievedChunk` builder |

### Coverage
Every stage has dedicated unit tests; the integration test exercises the whole engine
(query → engineered context) and asserts the invariants (no overflow, citations preserved).

```bash
cd backend
./venv/bin/python -m pytest tests/ -q                       # 65 tests, ~0.5s
./venv/bin/python -m pytest tests/test_context_builder.py -q
```

---

## 14. Performance Improvements

`scripts/run_context_eval.py` on the 10-query sample set (8192 window, reranker off):

| Metric | Value |
|---|---|
| Total context tokens (before → after) | **20,547 → 18,686** (**9.1%** reduction) |
| Mean compression ratio | 0.063 |
| Mean duplicate reduction rate | 0.100 |
| **Mean citation coverage** | **1.000** |
| Mean context relevance | 0.606 |
| Mean context density | 0.319 |

### Before vs After

| Aspect | Before Phase 2 | After Phase 2 |
|---|---|---|
| Context construction | raw concat, wrong builder, no `[n]` | dedup → rank → budget → compress → assemble |
| Token usage | unbounded, unmeasured | budgeted, **provably fits** window, measured |
| Duplicates | sent to LLM | ~10% removed (exact/near/structural) |
| Citations | display-only dedup, could be dropped | **100% preserved**, inline `[n]` markers |
| Latency added | n/a | **sub-millisecond** (pure CPU, no model calls) |

### Honest interpretation
- The **9.1%** token saving is modest **by design at an 8192 window**: when everything
  already fits, the budget rarely triggers compression, so savings come mostly from
  deduplication (~10%). Under a smaller window / more candidates, `compress_to_fit` engages
  and the ratio rises — `test_budget_prevents_overflow_with_many_chunks` exercises that path.
- The headline wins are **guaranteed overflow safety** and **100% citation preservation** —
  grounding and safety became *guaranteed*, which matters more than the raw token percentage
  on this small, low-duplication corpus.

---

## 15. File Changes Summary

### New files
| File | Purpose |
|---|---|
| `backend/app/context/__init__.py` | package surface |
| `backend/app/context/schemas.py` | `Evidence`, `Citation`, `ContextResult` |
| `backend/app/context/tokenizer.py` | pluggable `TokenCounter` + heuristic |
| `backend/app/context/budget.py` | `TokenBudgetManager`, `Budget` |
| `backend/app/context/dedup.py` | `DuplicateChunkDetector` |
| `backend/app/context/ranking.py` | `EvidenceRanker` |
| `backend/app/context/compression.py` | `ContextCompressor` + strategies (extractive / LLM seam) |
| `backend/app/context/assembly.py` | `ContextAssembler` |
| `backend/app/context/metrics.py` | context quality metrics |
| `backend/app/context/builder.py` | `ContextBuilderService` orchestrator |
| `backend/scripts/run_context_eval.py` | before/after eval runner |
| `backend/tests/test_{budget,dedup,ranking,compression,assembly,context_metrics,context_builder,context_helpers}.py` | tests |
| `phase2.md` | this document |

### Modified files
| File | Change |
|---|---|
| `backend/app/api/query.py` | runs `context_builder.build()` between retrieval and LLM; returns `context` metrics |
| `backend/app/services/answer_service.py` | consumes engineered context (no own builder); `format_citations()`; LLM model from config |
| `backend/app/core/state.py` | builds `context_builder` singleton |
| `backend/app/core/config.py` | context-window, reserves, dedup threshold, compression toggle |

### Architectural impact
- The **retrieval→LLM seam is now single and correct** — the duplicate-builder conflict is gone.
- A new, **independently testable** `app/context/` layer sits between Phase-1 retrieval and
  the LLM, with one stable entry point (`ContextBuilderService.build`) that future agents and
  modalities reuse.
- Token budgeting introduces **window-overflow safety** the system never had.

---

## 16. Developer Guide

### Add a compression strategy (e.g. real LLM compression)
Implement the `CompressionStrategy` protocol and inject it:
```python
class MyLLMStrategy:
    def summarize(self, text, target_tokens, query_keywords, counter) -> str: ...
compressor = ContextCompressor(counter, strategy=MyLLMStrategy())
ContextBuilderService(compressor=compressor, ...)
```

### Add a ranking method / change weights
```python
ranker = EvidenceRanker(retrieval_weight=0.5, metadata_weight=0.3, citation_weight=0.2)
ContextBuilderService(ranker=ranker, ...)
```
For a brand-new signal, add it to `EvidenceRanker.rank` and include it in the weighted sum.

### Add token management rules
- Swap the counter: `TokenCounter(count_fn=my_tokenizer.count)`.
- Change reserves/window via env (`LEXIMIND_CONTEXT_WINDOW`, `LEXIMIND_SYSTEM_RESERVE`,
  `LEXIMIND_RESPONSE_RESERVE`) or constructor args.
- Custom fit policy: pass a `cost_fn` to `TokenBudgetManager.greedy_fit`.

### Extend context assembly
Edit `ContextAssembler.assemble` (e.g. add section sub-headers, change the citation label
format, or insert group separators). Keep it pure (evidence in → string + citations out) and
add an `test_assembly.py` case.

### Add a new context stage
Create a pure stage class under `app/context/`, call it at the right point in
`ContextBuilderService.build`, and add a unit test. Pure (in → out, no I/O) keeps it testable.

---

## 17. Connection to Future Phases

```
                ContextResult { context, evidence, citations, metrics }
                                   │  stable contract every later phase consumes
        ┌──────────────────────────┼───────────────────────────┬───────────────────┐
        ▼                          ▼                            ▼                   ▼
   Product V1 (Phase 2/UI)   Multimodal (Phase 3–5)     Agents (Phase 6)     Knowledge Graph (Phase 7)
   - render [n] citations    - image/audio become         - Verifier reads      - entities from
     from ctx.citations        Evidence; same dedup→         citations+metrics     evidence.citations
   - show context metrics      rank→budget→assemble         to check grounding   - graph facts become
     (density, coverage)        path, grouped by doc       - Planner uses          Evidence merged with
                                                            metrics to decide       text evidence via the
                                                            retrieve/compress more  same pipeline
```

| Future capability | What Phase 2 provides |
|---|---|
| **Product V1** | `[n]` markers + `List[Citation]` → clickable citation UI; `ctx.metrics` → quality display |
| **Multimodal Retrieval** | new modalities arrive as `Evidence` and flow through the *same* engine |
| **Agents** | one stable `build()` boundary + metrics for planner/verifier decisions |
| **Knowledge Graph** | stable `document_id`/`chunk_id` + citations anchor entity/concept links; graph facts fuse as `Evidence` |
| **Token Optimization (pillar)** | budgeting + compression are the foundation |
| **Faithfulness/Citation evals (Phase 8)** | citation coverage + density metrics already produced |

---

## 18. Lessons Learned

### Decisions
- **Wrap, don't mutate** — `Evidence` keeps the retrieval contract clean while context stages
  annotate freely.
- **Rank before dedup** — survivor selection needs the score; a documented deviation from the
  listed stage order.
- **Budget on rendered cost** — budgeting raw text under-counts citation headers and can still
  overflow; budgeting the assembled block guarantees fit. (Caught by a test, then fixed.)
- **Never under-count tokens** — the heuristic counter takes the *max* of two estimates so the
  one failure the budgeter exists to prevent can't slip through.

### Tradeoffs
- Extractive (not abstractive) compression for now — deterministic, offline, no quality risk;
  the LLM-compression seam is ready when needed.
- Lexical (Jaccard) dedup rather than embedding-similarity dedup — fast and offline; may miss
  heavily paraphrased duplicates (acceptable; revisit if observed).
- Heuristic token counting, not llama3-exact — conservative by design.

### Known limitations
- Modest token savings on a large window / low-duplication corpus (§14); value shows under
  tighter budgets.
- Compression is sentence-level extractive; no cross-document synthesis yet.
- Token counts approximate the true llama3 tokenization.

### Future improvements
1. Wire `LLMCompressionStrategy` to a local Ollama model for abstractive compression.
2. Inject a precise tokenizer for exact budgeting.
3. Optional embedding-based near-duplicate detection (higher recall).
4. Streaming assembly + answer once the response path is async.
5. Surface `ctx.metrics` in the API response and (Product V1) the UI.
```
