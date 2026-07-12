# Phase 7 — Module 1: Knowledge Extraction & Graph Construction

> **Status:** ✅ Complete · Backend `app/knowledge/` · Frontend `KnowledgeGraphInspector` · 19 new tests. Deterministic + LLM-free extraction (works everywhere, injectable engine seam for a future model). Storage-agnostic behind a `GraphStore` interface. This module BUILDS + MAINTAINS the graph — retrieval/reasoning is Module 2+.

---

## 1. Module Overview

Until now LexiMind stored **chunks** — isolated slices of text with embeddings. It could *find* passages
but didn't *understand* the concepts they described. This module makes LexiMind **knowledge-centric**:
it continuously extracts **entities** (people, orgs, technologies, languages, frameworks, algorithms,
data structures, concepts, …) and **typed relationships** (uses, implements, depends_on, part_of,
created_by, …) from every modality and assembles them into a **workspace-scoped Semantic Knowledge
Graph** with canonical resolution, deduplication, provenance, versioning, and integrity validation.

**Document storage vs semantic knowledge:**

| Document/chunk storage (before) | Semantic knowledge (this module) |
|---|---|
| Isolated chunks + embeddings | Canonical entities + typed relationships |
| "Which passages mention X?" | "What *is* X, what does it depend on, who made it?" |
| No cross-document links | One canonical node per concept across all documents/modalities |
| Duplicates everywhere ("LLM" ≠ "Large Language Model") | Resolution + dedup → a single canonical node with aliases |
| No provenance graph | Every node/edge carries source refs + evidence |

Every future capability (graph retrieval, graph reasoning, the interactive knowledge workspace,
enterprise knowledge management) builds on this graph.

---

## 2. Previous Architecture

```
Documents → Chunks → Embeddings → Retrieval
```

Knowledge lived only as vectors + text. Limitations: no concept-level model, no cross-document identity
(the same idea appeared as many unrelated chunks), no relationships, no way to ask structural questions,
and no substrate for reasoning or knowledge management.

---

## 3. New Architecture

```
Document / Recording
   ↓   (REUSES existing processing — no re-processing)
Chunks (MultimodalChunk · MediaChunk · TranscriptSegment)   ← ingestion / media / vision pipelines
   ↓
Entity Extraction  ── gazetteer + acronym defs + proper-noun spans
   ↓
Relationship Extraction  ── entity co-occurrence + cue patterns
   ↓
Resolution + Deduplication  ── canonical node per concept (aliases mapped in)
   ↓
Versioning + Provenance  ── monotonic version, source_refs, edge evidence
   ↓
Graph Validation  ── integrity report
   ↓
Graph Storage (GraphStore interface → SqlGraphStore)   ← storage-agnostic
   ↓
GraphConstructionLog  → future Graph Retrieval (Module 2)
```

Graph construction is **another background stage after ingestion** (like vision/media processing) — it
never blocks uploads and builds incrementally.

---

## 4. Knowledge Extraction Pipeline

1. **Sources** (`sources.py`) — collect extractable text by REUSING existing outputs:
   `MultimodalChunk.content` (text/ocr/table/figure/image captions), `MediaChunk.content` +
   `TranscriptSegment.text` (audio/video), plus the document title/description. Cross-modal, no re-processing.
2. **Entity extraction** (`extraction.py`, per sentence) — gazetteer match (high-confidence typing +
   canonicalization), acronym definitions ("Large Language Model (LLM)" → canonical + alias), and
   capitalized multi-word proper-noun spans (candidate concepts/orgs). Each carries a provenance ref.
3. **Relationship extraction** — entities co-occurring in a sentence; the text BETWEEN them is matched
   against cue patterns → a typed directed edge (`uses`/`depends_on`/`created_by`/…), else weak `related_to`.
4. **Resolution + dedup** (`resolution.py`) — an in-memory index of the workspace's existing canonicals +
   aliases (normalized) matches each extraction to its node → merge (union aliases/provenance, bump
   mention_count + version) or create. Handles cross-document/cross-modal identity ("Node.js" == "NodeJS").
5. **Validation** (`validator.py`) — broken/invalid/self-loop/duplicate-edge/orphan checks → report.
6. **Versioning** — monotonic `version` on merge/update + soft-delete (merge/restore) + the construction
   log as history (time-travel is future).
7. **Background processing** (`runner.py`) — threadpool runner (prod) / InlineRunner (tests); incremental.

---

## 5. Backend Architecture

```
app/knowledge/
  validation.py    vocabularies (ENTITY_TYPES / RELATIONSHIP_TYPES) + normalize_name
  gazetteer.py     curated known-entity KB + relationship cue patterns
  extraction.py    EntityExtractor + RelationshipExtractor (deterministic; injectable seam)
  resolution.py    GraphResolver (canonicalization + dedup index)
  validator.py     GraphValidator → ValidationReport
  sources.py       cross-modal TextSource collectors (reuse chunk tables)
  storage.py       GraphStore Protocol (Neo4j/AGE/Postgres-agnostic)
  repository.py    GraphRepository (SQL GraphStore + metrics)
  builder.py       GraphBuilder (extract→resolve→dedup→version→store→validate; incremental)
  events.py        GraphEventPublisher seam
  models.py        GraphEntity / GraphRelationship / GraphConstructionLog
  service.py       KnowledgeGraphService (build / ensure / search / stats / validate / logs / contribute)
  runner.py        GraphRunner (threadpool) + InlineRunner
  schemas.py / api.py  DTOs + /workspaces/{id}/graph/* routes
  errors.py        transport-agnostic errors (status_code)
```

- **Interfaces / DI** — the builder/service depend on the `GraphStore` Protocol, not SQLAlchemy; the
  extractors are injectable (deterministic default → future spaCy/LLM). The API injects the runner via
  `get_graph_runner` (tests override to InlineRunner).
- **Caching / incremental** — the resolver is seeded from the persisted graph so a new document merges
  instead of rebuilding; `ensure_built` is a citations-style staleness guard (build only if no completed
  log exists / forced). Provenance + evidence are capped to bound row size.
- **Validation / errors** — Pydantic bounds; `EntityNotFound`/`DocumentNotFound`/`GraphLogNotFound` → 404.
- **Error handling** — the prod runner writes a `queued` log then marks `completed`/`failed`; agent
  contribution is fully guarded (a graph hiccup never affects the agent run).

---

## 6. Graph Data Model

- **GraphEntity** — `id, workspace_id, owner_id, entity_type, canonical_name, normalized_name (dedup key),
  aliases[], description, confidence, mention_count, degree, source_refs[], status (active/merged/deleted),
  merged_into, version, deleted_at`. Indexed on `(workspace, normalized_name)`, `(workspace, type)`,
  `(workspace, status)`.
- **GraphRelationship** — `id, workspace, owner, source_id, target_id, rel_type, directed, weight,
  confidence, mention_count, evidence[], status, version`. Indexed on source/target/type.
- **GraphConstructionLog** — per-build telemetry (counts, validation, confidence, timing, report JSON).
- **Workspace isolation** — every row + query is workspace + owner scoped.
- **Extensibility** — plain rows + JSON provenance are storage-agnostic (map onto Neo4j/AGE nodes+edges);
  `ENTITY_TYPES` extends for user-defined types; the `GraphStore` interface swaps the backend.

---

## 7. AI Integration (no duplicated pipelines)

- **Retrieval / Context / Multimodal / Temporal** — graph construction READS the chunks those pipelines
  already produced (`MultimodalChunk`, `MediaChunk`, `TranscriptSegment`); it never re-runs OCR/ASR/embedding.
- **Agent Framework** — `AgentTaskService.run_task` optionally contributes each agent's answer to the graph
  (`contribute_graph` flag) through the SAME `KnowledgeGraphService.contribute_from_text` → same extraction
  pipeline, no duplication (Step 16).
- **Verification Engine** — the same deterministic-primitive philosophy (Module 3's `textutil.sentences`
  is reused for sentence splitting); the validator plays the "integrity verification" role for the graph.
- No new retrieval/inference pipeline is introduced.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/graph`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/build` | Build the whole workspace graph (background runner) → GraphConstructionLog |
| POST | `/documents/{document_id}/build` | Build one document's graph (incremental) |
| POST | `/extract` | Ad-hoc extraction from raw text (developer + agent-contribution) → log + report |
| GET | `/entities?query=&type=&limit=` | Entity search (by name / type) |
| GET | `/entities/{entity_id}` | Entity detail + its relationships |
| GET | `/relationships?type=&limit=` | Relationship search |
| GET | `/stats` | Graph statistics (counts, type distributions, density) |
| GET | `/validate` | Integrity validation report |
| GET | `/logs` · `/logs/{id}` | Construction history + detail |

**Errors:** 404 workspace/document/entity/log, 401/403 unauthenticated, 422 bad params.

---

## 9. Performance Optimizations

- **Incremental** — the resolver is seeded from the persisted graph; a new document merges without
  rebuilding (never rebuild from scratch); `ensure_built` skips already-built documents.
- **Batch extraction** — a whole document/workspace is one build pass; entity index is built once per build.
- **Caching / bounded rows** — normalized dedup index + capped `source_refs`/`evidence`; `degree` cached
  on the node.
- **Parallel-ready** — the runner is a threadpool; the `GraphEventPublisher` seam supports downstream
  index sync; large workspaces process document-by-document.
- **Scalability seam** — the `GraphStore` interface lets a graph DB (Neo4j/AGE) back millions of nodes
  without touching the builder/service (SQL is the Module-1 implementation).

---

## 10. Testing

- **`tests/test_knowledge_unit.py` (10)** — normalization, gazetteer resolution + cues, entity extraction
  (gazetteer/acronym/proper-noun + no cross-sentence false positives), typed+directed relationship
  extraction, resolver alias matching, validator (broken/self-loop/orphan), and the full builder
  (incremental merge + versioning + provenance, cross-normalization dedup "Node.js"=="NodeJS").
- **`tests/test_knowledge_api.py` (9)** — ad-hoc `/extract` (entities typed + searchable, relationships
  with named endpoints, entity detail), incremental dedup over HTTP, **document build reusing ingested
  chunks**, workspace build + logs, stats + validation, type filter, **agent auto-contribution** (a
  research task with `contribute_graph=True` populates the graph via the wired hook), auth, 404.
- **Regression** — new models registered in `init_db` + conftest; the graph runner overridden to
  InlineRunner. All Phase 1–6 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/knowledge/{__init__,validation,gazetteer,extraction,resolution,validator,
sources,storage,repository,builder,events,models,service,runner,schemas,api,errors}.py`;
`tests/test_knowledge_unit.py`; `tests/test_knowledge_api.py`.

**Modified (backend)** — `app/db/base.py` (register 3 models), `app/main.py` (mount router),
`tests/conftest.py` (register models + mount router + InlineRunner override),
`app/agents/task_service.py` (agent-contribution hook), `app/agents/task_schemas.py` +
`app/agents/task_api.py` (`contribute_graph` flag).

**New (frontend)** — `src/api/knowledge.ts`; `src/pages/KnowledgeGraphInspector.tsx`;
`src/styles/knowledge.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

---

## 12. Future Compatibility

- **Module 2 — Semantic Memory & Graph Retrieval** — the graph + `GraphStore` interface + entity/edge
  provenance are exactly what graph-aware retrieval walks; `degree`/`weight`/`confidence` are ranking signals.
- **Module 3 — Graph Reasoning** — typed edges + evidence support path/inference queries; the versioning
  + validation give a trustworthy substrate.
- **Module 4 — Interactive Knowledge Workspace** — this module's inspector is the developer precursor to
  the visual graph UI (which consumes the same entity/relationship APIs).
- **Enterprise Knowledge Management** — workspace isolation + provenance + construction logs are the audit
  substrate; the storage abstraction allows a managed graph DB.
- **AI Agents / Knowledge Discovery** — agents already contribute knowledge; the graph becomes shared
  long-term memory across runs (the Phase-6 SharedContextManager can read it next).

---

## 13. Lessons Learned

- **Reuse the pipeline outputs, don't re-process.** Reading `MultimodalChunk`/`MediaChunk`/`TranscriptSegment`
  meant graph construction added zero OCR/ASR/embedding cost and instantly covered every modality.
- **Deterministic-first extraction.** A gazetteer + acronym/proper-noun heuristics + cue patterns produce
  a useful, *testable*, torch-free graph today, with the extractors behind an interface so a spaCy/LLM
  engine upgrades quality later without touching the builder — the same "Fake engine in tests, real
  engine lazy in prod" pattern the rest of LexiMind uses.
- **Precision matters in extraction too.** Processing per-sentence (not per-document) killed cross-sentence
  false positives like "Node.js" + "FAISS" being fused into one bogus entity — echoing the Module-3 lesson
  that noisy signals are worse than fewer clean ones.
- **Resolution/dedup is the whole point.** Seeding the resolver from the persisted graph makes identity
  (one canonical node per concept, aliases mapped in) fall out incrementally across documents and modalities.
- **Tradeoffs / limitations.** Extraction is heuristic (recall/precision below a trained NER/RE model — the
  injectable seam is the upgrade path); resolution is lexical (embedding-similarity dedup is a declared
  future signal); versioning is version-int + soft-delete + log (full time-travel is future); the resolver
  loads the workspace's entities into memory per build (fine for incremental single-document builds; a
  graph-DB backend handles millions). Storage is SQL now, but nothing above the `GraphStore` interface
  assumes it.
