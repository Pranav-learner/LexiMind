"""Graph Reasoner (Step 2) — the reasoning orchestrator.

Pipeline (each stage injectable; reuses Module-1 graph + Module-2 recognition + Phase-6 verification):

    query → recognize seeds → build adjacency → enumerate paths → infer relationships
          → propagate confidence → graph-verify → explain → reasoning-aware context

It owns NO retrieval and NO inference (LLM) path — it reasons over the graph the earlier modules built,
and hands a reasoning-context block to the single PromptPackage → AnswerService pathway (via the
`graph_reason` agent tool). A subgraph-keyed cache avoids repeated reasoning.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.graphreason.cache import REASONING_CACHE
from app.graphreason.confidence import ConfidencePropagation
from app.graphreason.context import build_reasoning_context
from app.graphreason.dependency import DependencyAnalyzer
from app.graphreason.explanation import ExplanationBuilder
from app.graphreason.inference import RelationshipInference
from app.graphreason.interfaces import ReasoningResult
from app.graphreason.paths import PathReasoner, build_adjacency
from app.graphreason.verification import GraphVerificationAdapter
from app.knowledge.repository import GraphRepository
from app.memory.recognition import QueryEntityRecognizer


class GraphReasoner:
    pipeline_version = "graphreason-v1"

    def __init__(self, db, *, recognizer=None, path_reasoner=None, inferer=None, propagator=None,
                 explainer=None, verifier=None):
        self.db = db
        self.graph = GraphRepository(db)
        self.recognizer = recognizer or QueryEntityRecognizer()
        self.path_reasoner = path_reasoner or PathReasoner()
        self.inferer = inferer or RelationshipInference()
        self.propagator = propagator or ConfidencePropagation()
        self.explainer = explainer or ExplanationBuilder()
        self.verifier = verifier or GraphVerificationAdapter()

    def reason(self, workspace_id: str, owner_id: str, *, query: str, hops: int = 3, directed: bool = False,
               max_paths: int = 40, seed_entity_ids: Optional[List[str]] = None, verify: bool = True,
               dependency: bool = False, use_cache: bool = True) -> ReasoningResult:
        t0 = time.perf_counter()
        timings: Dict[str, float] = {}
        result = ReasoningResult(query=query)

        # 1) recognize seeds
        t = time.perf_counter()
        if seed_entity_ids:
            entities = self.graph.workspace_entities(workspace_id, owner_id)
            seeds = [e for e in entities if e.id in set(seed_entity_ids)]
        else:
            seeds = self.recognizer.recognize(query, workspace_id, owner_id, repo=self.graph)
        result.seeds = [{"id": s.id, "name": s.canonical_name, "type": s.entity_type} for s in seeds]
        timings["recognition_ms"] = (time.perf_counter() - t) * 1000
        seed_ids = [s.id for s in seeds]

        cached = REASONING_CACHE.get(workspace_id, seed_ids, hops, directed) if use_cache else None
        if cached is not None:
            cached.cache_hit = True
            return cached

        # 2) build adjacency over the workspace graph
        entities_by_id = {e.id: e for e in self.graph.workspace_entities(workspace_id, owner_id)}
        edges = self.graph.workspace_relationships(workspace_id, owner_id, limit=5000)
        adj = build_adjacency(edges, entities_by_id, directed=directed)
        adj_dir = build_adjacency(edges, entities_by_id, directed=True)

        # 3) multi-hop paths
        t = time.perf_counter()
        paths = self.path_reasoner.find_paths(adj, entities_by_id, seed_ids, hops=hops, directed=directed,
                                              max_paths=max_paths)
        result.paths = paths
        timings["paths_ms"] = (time.perf_counter() - t) * 1000

        # 4) relationship inference
        t = time.perf_counter()
        result.inferences = self.inferer.infer(paths)
        timings["inference_ms"] = (time.perf_counter() - t) * 1000

        # 5) dependency / root-cause (optional)
        if dependency and seed_ids:
            chains, root_causes = DependencyAnalyzer().analyze(adj_dir, entities_by_id, seed_ids[0])
            result.dependencies = chains
            result.root_causes = root_causes

        # 6) graph verification (reuse Verification Engine + topology check)
        t = time.perf_counter()
        subgraph_nodes = {nid: entities_by_id[nid] for p in paths for nid in p.node_ids if nid in entities_by_id}
        subgraph_edges = {e.rel_id: e for p in paths for e in p.edges}
        edge_rows = [er for er in edges if er.id in subgraph_edges]
        ver = None
        if verify:
            ver = self.verifier.verify(self.db, workspace_id, owner_id,
                                       subgraph_entities=list(subgraph_nodes.values()),
                                       subgraph_edges=edge_rows, inferences=result.inferences, paths=paths,
                                       verify_conclusions=False)
            result.verification = ver
        timings["verification_ms"] = (time.perf_counter() - t) * 1000

        # 7) confidence propagation
        t = time.perf_counter()
        signals = {"verification": (ver or {}).get("signal", 0.6), "seed_count": len(seeds)}
        result.confidence = self.propagator.propagate(paths, result.inferences,
                                                      node_index=subgraph_nodes or entities_by_id,
                                                      signals_in=signals)
        timings["confidence_ms"] = (time.perf_counter() - t) * 1000

        # 8) context + 9) explanation
        ctx = build_reasoning_context(result)
        result.context_text = ctx["context_text"]
        result.citations = ctx["citations"]
        result.explanation = self.explainer.build(result)

        result.complexity = {"seeds": len(seeds), "nodes": len(subgraph_nodes), "edges": len(subgraph_edges),
                             "paths": len(paths), "inferences": len(result.inferences),
                             "max_depth": max((p.length for p in paths), default=0)}
        timings["total_ms"] = (time.perf_counter() - t0) * 1000
        result.timings = {k: round(v, 3) for k, v in timings.items()}

        if use_cache:
            REASONING_CACHE.put(workspace_id, seed_ids, hops, directed, result)
        return result
