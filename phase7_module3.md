# Phase 7 — Module 3: Graph Reasoning & Explainable AI

> **Status:** ✅ Complete · Backend `app/graphreason/` · Frontend `GraphReasoningInspector` · 19 new tests. The graph becomes a reasoning engine: multi-hop paths, transitive relationship inference, confidence propagation, dependency/root-cause analysis, graph-assisted verification (reusing the Verification Engine), and structured explainable metadata — all LLM-free, feeding the single PromptPackage → AnswerService pathway via the `graph_reason` agent tool.

---

## 1. Module Overview

Modules 1–2 built and retrieved the knowledge graph. This module makes it **reason**: it discovers
implicit relationships, follows dependency chains to root causes, propagates confidence through connected
evidence, verifies conclusions against graph topology, and explains *why* a conclusion was reached.

**Graph retrieval vs graph reasoning:**

| Graph retrieval (Module 2) | Graph reasoning (this module) |
|---|---|
| "What is connected to X?" (neighborhood) | "How is X connected to Y, and what does that imply?" (paths) |
| Returns hits | Returns reasoning paths + inferred relationships |
| Similarity/proximity | Transitive inference (A uses B, B depends on C → A depends on C) |
| Node/edge scores | Confidence propagated evidence → edges → paths → conclusion |
| No structure implied | Dependency chains, root causes, contradictions |
| — | Explainable reasoning (why this conclusion / these entities / these relationships) |

Reasoning does not introduce a new LLM path — it reasons over the graph and hands a reasoning-context
block to the existing PromptPackage → AnswerService pathway.

---

## 2. Previous Architecture

```
Query → Graph Retrieval → Context → PromptPackage → AnswerService
```

Limitations: the graph was used only for *retrieval*. It couldn't infer implicit relationships, follow
multi-hop dependency chains, find root causes, propagate confidence, or explain its reasoning — so
structural questions ("what does X ultimately depend on?", "why is this true?") had no first-class answer.

---

## 3. New Architecture

```
Query
  ↓
Entity Recognition        (reuses Module-2 recognizer → graph seeds)
  ↓
Multi-Hop Path Reasoning  (DFS, weighted, cycle-protected, depth-limited)
  ↓
Relationship Inference    (transitive composition → inferred edges, kept SEPARATE)
  ↓
Confidence Propagation    (evidence → edges → paths → overall; reuses Phase-6 ConfidenceBreakdown)
  ↓
Graph Verification        (topology + conclusions; REUSES GraphValidator + VerificationService)
  ↓
Explainable Reasoning     (structured metadata; no chain-of-thought)
  ↓
Reasoning-aware Context → PromptPackage → AnswerService   (single inference pathway; via graph_reason tool)
```

---

## 4. Graph Reasoning Pipeline

1. **Multi-hop reasoning** (`paths.py`) — build adjacency (directed/undirected) from the graph, enumerate
   reasoning paths via DFS to `hops`, with cycle protection, weighted pruning, and a path cap.
2. **Relationship inference** (`inference.py`) — fold each path's relationship chain through a transitive
   composition table (`uses ∘ depends_on → depends_on`, `part_of ∘ part_of → part_of`, …) → INFERRED edges
   with confidence, kept SEPARATE from extracted (persisted `status="inferred"`, invisible to retrieval).
3. **Confidence propagation** (`confidence.py`) — node/edge/path/overall confidence from measurable signals
   (path confidence, graph confidence, evidence strength, verification, connectivity); reuses the Phase-6
   `ConfidenceBreakdown`/`ConfidenceSignal`.
4. **Graph verification** (`verification.py`) — topology consistency (reuse Module-1 `GraphValidator`) +
   conflicting-inference detection + optional conclusion check (reuse Phase-6 `VerificationService`).
5. **Dependency analysis** (`dependency.py`) — directed dependency chains from an entity.
6. **Root-cause analysis** — terminal nodes of the dependency chains = foundational dependencies / causes.
7. **Explainable AI** (`explanation.py`) — reasoning paths, entity/relationship/evidence chains, confidence
   breakdown, verification + citation summaries, and "why" answers — structured, no chain-of-thought.

---

## 5. Backend Architecture

```
app/graphreason/
  interfaces.py    ReasoningPath / ReasonedRelationship / DependencyChain / ReasoningResult + Protocols
  paths.py         PathReasoner (multi-hop DFS) + build_adjacency
  inference.py     RelationshipInference (transitive composition rules)
  confidence.py    ConfidencePropagation (reuses Phase-6 ConfidenceBreakdown)
  dependency.py    DependencyAnalyzer + root cause
  verification.py  GraphVerificationAdapter (reuses GraphValidator + VerificationService)
  explanation.py   ExplanationBuilder (structured; no chain-of-thought)
  context.py       reasoning-aware context assembly
  cache.py         ReasoningCache (LRU over subgraphs)
  engine.py        GraphReasoner (orchestrator)
  models.py        GraphReasoningLog
  repository.py    ReasoningRepository (log + inferred-edge persistence)
  service.py       GraphReasoningService
  schemas.py / api.py  DTOs + /workspaces/{id}/reasoning/* routes
  errors.py        transport-agnostic errors (status_code)
```

- **Interfaces / DI** — path reasoner, inferer, propagator, verifier, explainer are replaceable Protocols;
  the engine composes them (a future GNN/rule-learner drops in unchanged).
- **Reuse** — Module-1 graph store, Module-2 recognizer, Phase-6 `GraphValidator` + `VerificationService` +
  `ConfidenceBreakdown`. No reasoning/verification/retrieval logic is duplicated.
- **Validation / errors** — Pydantic bounds (hops 1–5); `EntityNotFound`/`ReasoningLogNotFound` → 404.
- **Error handling** — inferred-edge persistence + conclusion verification are best-effort (rollback +
  degrade); the `graph_reason` tool is a cheap no-op on an empty graph.

---

## 6. Explainable AI Architecture

- **Reasoning paths** — ordered entity/relationship chains (`A —uses→ B —depends_on→ C`) + path confidence.
- **Confidence model** — node/edge/path/overall, each an explainable weighted signal blend (measurable,
  not LLM self-report).
- **Evidence chains** — the supporting sentences attached to each traversed edge.
- **Relationship chains** — the typed relationship sequence per path.
- **Verification** — topology consistency + conflicting-path detection + optional conclusion verification.
- **Developer inspection** — the `/reasoning/explain` endpoint + the inspector page expose all of the above
  as structured metadata (never chain-of-thought).
- **Extensibility** — every stage is a Protocol; a GNN link-predictor or learned inference rules plug in.

---

## 7. AI Integration

- **Knowledge Graph / Semantic Memory** — reasoning reads the graph + reuses the Module-2 recognizer.
- **Retrieval Engine** — unchanged; reasoning is a layer AFTER retrieval, before context.
- **Context Engineering** — a reasoning-aware context block feeds the PromptPackage (complements Phase 2/4/M2).
- **Verification Engine** — reused for graph-topology + conclusion verification (Step 5).
- **Agent Runtime** — `graph_reason` is a registered tool + a default Research-Agent tool (Step 10);
  agents reason over the graph automatically, funnelled through the single PromptPackage → AnswerService.
- No duplicated reasoning pipeline; the single AnswerService inference path is preserved.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/reasoning`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| POST | `/reason` | Full reasoning: paths + inferences + confidence + verification + explanation |
| POST | `/preview` | Lightweight preview (paths + inferences; no persist) |
| POST | `/root-cause` | Root-cause analysis for a query |
| POST | `/explain` | Structured reasoning explanation |
| GET | `/entities/{id}/dependencies` | Dependency chains + root causes for an entity |
| GET | `/inferred` | List inferred (status=inferred) relationships |
| GET | `/stats` | Reasoning + inferred-edge + cache statistics |
| GET | `/logs` | Reasoning history |

**Reason response:** `{query, seeds[], paths[] (chain/edges/path_confidence), inferences[] (source/target/
rel_type/confidence/derivation/via), dependencies[], root_causes[], confidence{overall,band,signals,
node_confidence,edge_confidence_avg,path_confidence}, verification{graph_consistency,conflicting_paths,status},
explanation{}, context_text, citations[], complexity{}, timings{}, cache_hit}`.

**Errors:** 404 workspace/entity/log, 401/403 unauthenticated, 422 bad params.

---

## 9. Performance Optimizations

- **Reasoning cache** — subgraph-keyed LRU makes repeated/related queries O(1); path enumeration is the
  expensive step.
- **Traversal pruning** — hop limit + min-edge-weight floor + heaviest-first expansion + path cap.
- **Single load** — nodes + edges loaded once per reasoning.
- **Incremental / parallel-ready** — inference/propagation are pure functions over the enumerated paths;
  cache invalidation shares the Module-2 synchronizer's intent.
- **Cheap agent use** — `graph_reason` short-circuits on an empty graph.
- **Scalability** — the graph store abstraction (Module 1) is the seam for a graph DB / GNN backend.

---

## 10. Testing

- **`tests/test_graphreason_unit.py` (9)** — multi-hop paths (chains, cycle protection, cap), transitive
  inference (`_reduce_chain` + endpoint inference + multi-hop-only), confidence propagation (weights sum to
  1, node/edge/path/overall, explainable), dependency root-cause (Node.js terminal), explanation (structured,
  no CoT), reasoning cache, and the full reasoner.
- **`tests/test_graphreason_api.py` (10)** — the reasoning pipeline (paths + inferences + confidence +
  verification + explanation + timings + **inferred edges persisted as status=inferred** + log), cache hit,
  preview (no persist), root-cause (Node.js), entity dependency analysis, explain, stats, **agent
  integration** (`graph_reason` registered + used by the research agent), auth, 404.
- **Regression** — new model registered in `init_db` + conftest; `graph_reason` added to the tool registry
  + research agent (additive; the Module-2 gap unit test updated to keep the new tools empty). All Phase
  1–7 M2 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/graphreason/{__init__,interfaces,paths,inference,confidence,dependency,
verification,explanation,context,cache,engine,models,repository,service,schemas,api,errors}.py`;
`tests/test_graphreason_unit.py`; `tests/test_graphreason_api.py`.

**Modified (backend)** — `app/db/base.py` (register model), `app/main.py` (mount router),
`tests/conftest.py` (register model + mount router); `app/agents/tools/graph_tools.py` (+`GraphReasonTool`);
`app/agents/registry.py` (register `graph_reason` + descriptor); `app/agents/specialized/research_agent.py`
(add `graph_reason` to tool selection); `tests/test_research_agents_unit.py` (gap test keeps new tools empty).

**New (frontend)** — `src/api/reasoning.ts`; `src/pages/GraphReasoningInspector.tsx`; `src/styles/reasoning.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

---

## 12. Future Compatibility

- **Module 4 — Interactive Knowledge Workspace** — reasoning paths + confidence flow + root causes are the
  data the visual reasoning/graph UI renders.
- **Enterprise Explainable AI** — every conclusion carries a structured, auditable derivation + confidence.
- **Advanced AI agents** — `graph_reason` gives agents structural inference; the Multi-Agent orchestrator
  can route on reasoning confidence.
- **Graph Neural Networks** — the `PathReasoner`/`RelationshipInferer` Protocols are the drop-in points for
  a learned link-predictor / GNN; inferred edges already have a persistence lane.
- **Autonomous research** — contradictions + low-confidence inferences + gaps become research targets.
- **Long-term semantic memory** — inferred relationships accumulate in the graph as learned knowledge.

---

## 13. Lessons Learned

- **Reasoning = paths, not neighborhoods.** Enumerating *paths* (vs Module-2 neighborhoods) is what makes
  transitive inference, dependency chains, and root-cause analysis fall out — the same graph, a different traversal.
- **Keep inferred edges separate.** Persisting inferences as `status="inferred"` (invisible to retrieval's
  `active_only`) preserved the integrity of the extracted graph while making inferences queryable/auditable
  — no schema change, no retrieval pollution.
- **Reuse the confidence + verification value objects.** Propagation reused the Phase-6 `ConfidenceBreakdown`
  and the verification adapter reused `GraphValidator` + `VerificationService` — explainability and trust
  came for free, consistent with the rest of the platform.
- **Structure over chain-of-thought.** Explanations are the graph-grounded *structure* of the reasoning
  (paths, chains, signals) — auditable and safe to expose, unlike model deliberation.
- **Tradeoffs / limitations.** Inference is rule-based transitive composition (a GNN/link-predictor behind
  the same Protocol would infer non-transitive and probabilistic relationships); recognition inherits the
  Module-2 lexical limitation (single-word non-gazetteer entities may not seed); path enumeration is bounded
  (hop + path caps) so very large/dense graphs prune breadth — a graph-DB/GNN backend is the scale path.
  Conclusion verification is available but off by default in the agent tool to keep latency bounded.
