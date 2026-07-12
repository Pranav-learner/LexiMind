# Phase 7 — Module 2: Semantic Memory & Graph Retrieval

> **Status:** ✅ Complete · Backend `app/memory/` · Frontend `SemanticMemoryExplorer` · 21 new tests. The knowledge graph becomes a first-class retrieval source: query → entities → traversal → graph hits, fused with vectors through the EXISTING Phase-4 fusion (`graph` = a new modality). Graph retrieval is also an agent tool (`graph_search`). No retrieval pipeline is duplicated; the single PromptPackage → AnswerService pathway is preserved.

---

## 1. Module Overview

Module 1 built a passive knowledge graph. This module makes it an **active memory system**: instead of
retrieving isolated chunks, LexiMind resolves a query into **canonical entities**, traverses the graph
into a **semantic neighborhood**, and returns **knowledge** — entities, relationships, and evidence —
which is fused with vector/sparse/multimodal/temporal retrieval.

**Vector retrieval vs graph retrieval:**

| Vector retrieval (Phase 1) | Graph retrieval (this module) |
|---|---|
| "Which passages are similar to the query?" | "What entity is this about, and what is it connected to?" |
| Returns text chunks | Returns entities + typed relationships + neighborhoods |
| No structure | Structure-aware (hops, edges, centrality) |
| Similarity only | Relationship weight, distance, evidence, usage as signals |
| Per-document | Cumulative memory that survives document boundaries |

Graph retrieval doesn't replace vector retrieval — it becomes **another retrieval provider** fused into
the same ranking.

---

## 2. Previous Architecture

```
Query → Dense retrieval + Sparse retrieval → RRF fusion → Context
```

Limitations: retrieval was similarity-only; it couldn't answer structural questions ("what depends on
X?"), couldn't follow relationships, and had no cumulative cross-document memory — every query started
from raw vectors with no concept-level model, even though Module 1 had built one.

---

## 3. New Architecture

```
Query
  ↓
Entity Recognition   ── reuses Module-1 EntityExtractor + graph lookup → canonical seeds
  ↓
Traversal Engine     ── BFS/DFS N-hop, weighted, cycle-protected, cached  → Neighborhood
  ↓
Graph Retrievers     ── entity/neighbor/relationship/evidence/topic/concept/backlink/reference → GraphHits
  ↓
Memory Scoring       ── explainable signals (relationship weight · distance · confidence · evidence · usage)
  ↓
Hybrid Fusion        ── REUSES Phase-4 fuse() with `graph` as a modality (+ vector/multimodal/temporal)
  ↓
Graph-aware Context  ── dedup + rank + citation-preserving assembly
  ↓
PromptPackage → AnswerService   (single inference pathway; via the graph_search agent tool)
```

---

## 4. Semantic Memory Pipeline

1. **Entity recognition** (`recognition.py`) — reuses the Module-1 `EntityExtractor` + gazetteer to pull
   candidates from the query, matches them to EXISTING graph nodes (normalized name / alias), with a
   keyword-search fallback. "Explain virtual memory" → the `Virtual Memory` node.
2. **Traversal** (`traversal.py`) — loads active edges once, builds weighted adjacency, walks BFS/DFS to
   `hops`, with relationship-type filtering, node cap, cycle protection, workspace isolation. Configurable.
3. **Graph retrievers** (`retrievers.py`) — 8 retrievers (one interface) read the neighborhood into typed
   `GraphHit`s with hop distance + provenance.
4. **Memory scoring** (`scoring.py`) — `score = Σ signal·weight` over base-relevance, distance-decay,
   entity-confidence, relationship-weight, evidence-count, usage-frequency, graph-confidence — explainable.
5. **Hybrid fusion** (`fusion.py`) — adapts `GraphHit`→`RetrievalHit` (modality="graph") and calls the
   Phase-4 `fuse()` — the same weighted RRF, graph is just another modality.
6. **Graph-aware context** (`context.py`) — entity-aware dedup, relationship-aware ranking, concept-aware
   compression, graph-citation preservation → text + citations for the PromptPackage.
7. **Synchronization** (`service.MemorySynchronizer`) — ensure the graph is fresh (reuses Module-1
   `ensure_built`) + invalidate the neighborhood cache. Eventually consistent.
8. **Caching** (`cache.py`) — a bounded LRU of neighborhoods keyed by (workspace, seeds, hops, strategy,
   filter); invalidated on graph mutation.

---

## 5. Backend Architecture

```
app/memory/
  interfaces.py    GraphHit / Neighborhood / MemoryQuery + Protocols
  recognition.py   QueryEntityRecognizer (reuses Module-1 extraction)
  traversal.py     TraversalEngine (BFS/DFS/N-hop/weighted/cycle/filter/cap)
  retrievers.py    8 graph retrievers behind one interface
  scoring.py       MemoryScorer (explainable graph-signal scoring)
  fusion.py        hybrid_fuse — reuses app.mmretrieval.fusion.fuse
  context.py       graph-aware context assembly
  cache.py         NeighborhoodCache (LRU)
  models.py        SemanticMemoryLog
  repository.py    MemoryRepository (log) — graph reads via GraphRepository
  service.py       SemanticMemoryService + MemorySynchronizer
  schemas.py / api.py  DTOs + /workspaces/{id}/memory/* routes
  errors.py        transport-agnostic errors (status_code)
```

- **Interfaces / DI** — recognizer, traversal, retrievers, scorer are all replaceable Protocols; the
  service composes them. Graph reads go through the Module-1 `GraphRepository` (the `GraphStore`
  abstraction), so a graph-DB backend later needs no service change.
- **Reuse** — Module-1 extraction (recognition), Module-1 graph store (reads), Phase-4 `fuse` (hybrid),
  Phase-4 unified retrieval (the vector provider in hybrid mode). No new retrieval/fusion logic.
- **Validation / errors** — Pydantic bounds (hops 1–4, strategy pattern, max_nodes/limit caps);
  `EntityNotFound` → 404.
- **Error handling** — hybrid vector fetch is best-effort (rolls back + degrades to graph-only on failure);
  the `graph_search` tool is a cheap no-op when the workspace has no graph.

---

## 6. Graph Retrieval Architecture

- **Retriever interfaces** — `kind` + `retrieve(ctx) -> List[GraphHit]`, mirroring the Phase-4 multimodal
  retriever design (so the fusion is shared).
- **Traversal strategies** — BFS (FIFO) / DFS (LIFO), N-hop, weighted expansion (heavy edges first when
  capping), relationship filtering, node cap, cycle protection.
- **Fusion / ranking** — Phase-4 weighted RRF with per-modality weights (`graph` default 0.6); full
  fusion-contribution accounting is preserved.
- **Caching** — neighborhood LRU keyed by traversal params; workspace-scoped invalidation.
- **Workspace isolation** — every read is workspace + owner scoped (via GraphRepository).
- **Extensibility** — new retriever = a class + append to `ALL_RETRIEVERS`; new modality = add to the
  fusion dict + a weight; a graph-DB backend swaps behind `GraphStore`.

---

## 7. AI Integration

- **Knowledge Graph** — the source of truth for entities/relationships (read via `GraphRepository`).
- **Retrieval Engine** — graph is a NEW provider fused with the existing dense/sparse/multimodal/temporal
  via the Phase-4 `fuse` (not replaced).
- **Context Engineering** — graph-aware context produces PromptPackage-ready evidence (complements Phase 2/4).
- **Agent Runtime** — `graph_search` is a registered tool + a default Research-Agent tool (Step 15); agents
  automatically retrieve knowledge, funnelled through the same PromptPackage → AnswerService pathway.
- **Verification Engine** — graph relationships + evidence are available as structured claims to validate.
- No duplicated retrieval pipeline; the single AnswerService inference path is preserved.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/memory`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/retrieve` | Graph retrieval: recognize → traverse → retrieve → (hybrid fuse) → context |
| POST | `/recognize` | Resolve a query into canonical graph entities |
| GET | `/entities/{id}/neighborhood?hops=&strategy=` | Traversal preview around an entity |
| POST | `/sync` | Ensure the graph is fresh + invalidate the memory cache |
| GET | `/stats` | Memory + graph + cache statistics |
| GET | `/logs` | Semantic-memory query history |

**Retrieve request:** `{query, hops(1–4), strategy(bfs|dfs), rel_types?, max_nodes, limit, hybrid, seed_entity_ids?}`.
**Retrieve response:** `{query, mode, recognized_entities[], seed_count, neighborhood{nodes,edges,max_hop,truncated},
hits[] (kind/text/hop/score/signals), context_text, citations[], fused[] (modality/fusion_score/contributing_modalities),
cache_hit, avg_confidence, timings{recognition,traversal,retrieval,fusion,context,total}}`.

**Errors:** 404 workspace/entity, 401/403 unauthenticated, 422 bad params.

---

## 9. Performance Optimizations

- **Traversal caching** — the neighborhood LRU makes repeated/related queries O(1); traversal is the
  expensive step.
- **Traversal pruning** — node cap + weighted expansion + hop limit bound work on large graphs.
- **Single load** — edges + nodes are loaded once per traversal (no per-hop round-trips).
- **Parallel-ready** — retrievers are independent pure reads over the neighborhood.
- **Incremental sync** — reuses Module-1 incremental build + per-workspace cache invalidation.
- **Cheap agent use** — `graph_search` short-circuits when the graph is empty (one COUNT).
- **Scalability seam** — a graph-DB backend behind `GraphStore` handles millions of nodes with the same
  service.

---

## 10. Testing

- **`tests/test_memory_unit.py` (12)** — query recognition (+ keyword fallback), traversal (BFS hop
  distances, relationship filter, node cap/truncation, empty seeds), retrievers (typed hits), memory
  scoring (weights sum to 1, explainable signals, closer-hop-scores-higher), neighborhood cache
  (hit/miss/invalidate), hybrid fusion (reuses Phase-4 fuse; graph+vector ranked; graph-only), and
  graph-aware context (dedup + citations).
- **`tests/test_memory_api.py` (9)** — recognition, the full graph-retrieval pipeline (seeds + neighborhood
  + typed hits + context + citations + timings + **cache hit** on repeat + log persisted), **hybrid**
  fusion (graph as a fused modality), DFS + hop limit, entity neighborhood explorer, sync + stats, 404,
  auth, and **agent integration** (`graph_search` registered + used by the research agent).
- **Regression** — new model registered in `init_db` + conftest; `graph_search` added to the tool registry
  + research agent (additive). All Phase 1–7 M1 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/memory/{__init__,interfaces,recognition,traversal,retrievers,scoring,fusion,
context,cache,models,repository,service,schemas,api,errors}.py`; `app/agents/tools/graph_tools.py`;
`tests/test_memory_unit.py`; `tests/test_memory_api.py`.

**Modified (backend)** — `app/db/base.py` (register model), `app/main.py` (mount router),
`tests/conftest.py` (register model + mount router); `app/agents/registry.py` (register `graph_search` +
add to descriptors); `app/agents/specialized/research_agent.py` (add `graph_search` to tool selection).

**New (frontend)** — `src/api/memory.ts`; `src/pages/SemanticMemoryExplorer.tsx`; `src/styles/memory.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

---

## 12. Future Compatibility

- **Module 3 — Graph Reasoning & Explainable AI** — the scored hits + traversal paths + evidence are the
  substrate for multi-hop reasoning; the memory score is already explainable.
- **Module 4 — Interactive Knowledge Workspace** — the neighborhood/traversal APIs feed the visual graph UI.
- **Enterprise Semantic Search** — entity-resolved, structure-aware retrieval + workspace isolation.
- **Long-term Agent Memory** — the graph is cumulative cross-document memory; `graph_search` gives every
  agent access, and the Phase-6 SharedContextManager can read it across runs.
- **Autonomous Research** — graph gaps (low-degree nodes, missing relationships) become research targets.

---

## 13. Lessons Learned

- **Reuse the fusion, don't rebuild it.** Because Phase-4 `fuse()` was modality-agnostic ("add a modality
  + a weight"), graph retrieval slotted in as a first-class provider with zero fusion changes — the payoff
  of the earlier plug-and-play design.
- **Recognition is where graph retrieval lives or dies.** Reusing the Module-1 extractor + matching against
  actual graph nodes (not just extracting) means only real entities become seeds — precision over recall.
- **Cache the traversal, not the answer.** The neighborhood is the expensive, reusable artifact; caching it
  (invalidated on graph mutation) makes related queries cheap while staying consistent.
- **Explainable scores from measurable signals.** Following the Module-3 philosophy, the memory score is a
  weighted blend of graph-measurable signals (edge weight, hop, evidence, usage) — inspectable, not a black box.
- **Tradeoffs / limitations.** Recognition + traversal are lexical/structural (no embedding-similarity
  entity linking yet — a declared future signal); the resolver/traversal load workspace entities+edges into
  memory (fine at current scale; a graph-DB backend behind `GraphStore` handles millions); hybrid mode
  reuses the vector provider as-is (its own faiss path), so it degrades to graph-only without an index.
  Multi-hop *reasoning* over paths is deliberately deferred to Module 3 — this module retrieves, it doesn't infer.
