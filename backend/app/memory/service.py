"""Semantic Memory service — the graph-retrieval orchestrator (Steps 2–9, 11).

Pipeline (each stage injectable; reuses Module-1 graph + Phase-4 fusion — no duplicated retrieval):

    query → EntityRecognizer → TraversalEngine (cached) → GraphRetrievers → MemoryScorer
          → [hybrid fuse with vector retrieval] → graph-aware Context → SemanticMemoryLog

Also exposes the persistent-memory VIEWS over the graph (workspace/entity/relationship/topic memory —
the graph IS the cumulative memory that survives document boundaries) + a `MemorySynchronizer` that
keeps the graph + cache eventually consistent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.knowledge.repository import GraphRepository
from app.memory.cache import NEIGHBORHOOD_CACHE
from app.memory.context import build_graph_context
from app.memory.errors import EntityNotFound
from app.memory.fusion import hybrid_fuse
from app.memory.interfaces import MemoryQuery
from app.memory.models import SemanticMemoryLog
from app.memory.recognition import QueryEntityRecognizer
from app.memory.repository import MemoryRepository
from app.memory.retrievers import ALL_RETRIEVERS, RetrieverContext
from app.memory.scoring import MemoryScorer
from app.memory.traversal import TraversalEngine


class SemanticMemoryService:
    def __init__(self, db: Session, *, recognizer=None, scorer=None):
        self.db = db
        self.graph = GraphRepository(db)
        self.memory = MemoryRepository(db)
        self.recognizer = recognizer or QueryEntityRecognizer()
        self.scorer = scorer or MemoryScorer()

    # ------------------------------------------------------------------ retrieve (the main pipeline)
    def retrieve(self, workspace_id: str, owner_id: str, *, query: str, hops: int = 2,
                 strategy: str = "bfs", rel_types: Optional[List[str]] = None, max_nodes: int = 60,
                 limit: int = 20, hybrid: bool = False, seed_entity_ids: Optional[List[str]] = None,
                 persist: bool = True) -> Dict[str, Any]:
        t0 = time.perf_counter()
        mq = MemoryQuery(query=query, workspace_id=workspace_id, owner_id=owner_id, hops=hops,
                         strategy=strategy, rel_types=rel_types, max_nodes=max_nodes, limit=limit,
                         hybrid=hybrid, seed_entity_ids=seed_entity_ids or [])

        # 1) entity recognition
        t = time.perf_counter()
        if mq.seed_entity_ids:
            seeds = [e for e in self.graph.workspace_entities(workspace_id, owner_id)
                     if e.id in set(mq.seed_entity_ids)]
        else:
            seeds = self.recognizer.recognize(query, workspace_id, owner_id, repo=self.graph)
        recognition_ms = (time.perf_counter() - t) * 1000
        seed_ids = [s.id for s in seeds]

        # 2) traversal (cached)
        t = time.perf_counter()
        cached = NEIGHBORHOOD_CACHE.get(workspace_id, seed_ids, hops, strategy, rel_types)
        cache_hit = cached is not None
        if cache_hit:
            neighborhood = cached
        else:
            neighborhood = TraversalEngine().expand(self.graph, workspace_id, owner_id, seed_ids,
                                                    hops=hops, strategy=strategy, rel_types=rel_types,
                                                    max_nodes=max_nodes)
            NEIGHBORHOOD_CACHE.put(workspace_id, seed_ids, hops, strategy, rel_types, neighborhood)
        traversal_ms = (time.perf_counter() - t) * 1000

        # 3) graph retrievers + 4) scoring
        t = time.perf_counter()
        rctx = RetrieverContext(query=query, seeds=seeds, neighborhood=neighborhood)
        hits = []
        for r in ALL_RETRIEVERS:
            hits.extend(r.retrieve(rctx))
        for h in hits:
            self.scorer.score(h, node_index=neighborhood.nodes)
        retrieval_ms = (time.perf_counter() - t) * 1000

        # 5) hybrid fusion (optional) — reuse Phase-4 fusion with `graph` as a modality
        t = time.perf_counter()
        vector_hits = self._vector_hits(workspace_id, owner_id, query, mq.document_id) if hybrid else []
        fused = hybrid_fuse(hits, vector_hits)
        fusion_ms = (time.perf_counter() - t) * 1000

        # 6) graph-aware context
        t = time.perf_counter()
        ctx = build_graph_context(hits, limit=limit)
        context_ms = (time.perf_counter() - t) * 1000

        total_ms = (time.perf_counter() - t0) * 1000
        graph_hit_count = len(hits)
        vector_hit_count = len(vector_hits)
        avg_conf = round(sum(h.score for h in hits) / len(hits), 4) if hits else 0.0

        result = {
            "query": query, "mode": "hybrid" if hybrid else "graph",
            "recognized_entities": [{"id": s.id, "name": s.canonical_name, "type": s.entity_type} for s in seeds],
            "seed_count": len(seeds), "neighborhood": {"nodes": neighborhood.size,
                "edges": len(neighborhood.edges), "truncated": neighborhood.truncated,
                "max_hop": max(neighborhood.hop.values()) if neighborhood.hop else 0},
            "hits": ctx["hits"], "context_text": ctx["context_text"], "citations": ctx["citations"],
            "fused": [{"key": h.key, "modality": h.modality, "fusion_score": round(h.fusion_score, 6),
                       "content": h.content[:200], "contributing_modalities": h.contributing_modalities}
                      for h in fused[:limit]],
            "cache_hit": cache_hit, "avg_confidence": avg_conf,
            "timings": {"recognition_ms": round(recognition_ms, 3), "traversal_ms": round(traversal_ms, 3),
                        "retrieval_ms": round(retrieval_ms, 3), "fusion_ms": round(fusion_ms, 3),
                        "context_ms": round(context_ms, 3), "total_ms": round(total_ms, 3)},
        }
        if persist:
            self._persist(workspace_id, owner_id, query, seeds, neighborhood, strategy, hops,
                          graph_hit_count, vector_hit_count, cache_hit, avg_conf, result["timings"], hybrid)
        return result

    def _vector_hits(self, workspace_id, owner_id, query, document_id):
        """Best-effort vector retrieval (reuses the Phase-4 unified retrieval as the vector provider)."""
        try:
            from app.mmretrieval.repository import RetrievalRepository
            from app.mmretrieval.schemas import RetrievalHit, SearchRequest
            from app.mmretrieval.service import MultimodalRetrievalService
            svc = MultimodalRetrievalService(RetrievalRepository(self.db))
            res = svc.search(owner_id, workspace_id, SearchRequest(query=query, top_k=8,
                             document_id=document_id, explain=False))
            hits = []
            for i, r in enumerate(res.get("results", []), start=1):
                hits.append(RetrievalHit(
                    key=r.get("key") or f"chunk:{r.get('chunk_id') or i}", modality=r.get("modality", "text"),
                    source_type=r.get("source_type", "text_chunk"), document_id=r.get("document_id"),
                    content=r.get("content", ""), title=r.get("title", ""), chunk_id=r.get("chunk_id"),
                    normalized_score=max(0.0, 1.0 - (i - 1) * 0.1), rank_in_modality=i,
                    confidence=float(r.get("confidence", 0.5))))
            return hits
        except Exception:
            # the vector provider commits its own RetrievalLog; on failure, reset the session so the
            # graph-only pipeline + our SemanticMemoryLog persist still succeed (graceful degradation).
            try:
                self.db.rollback()
            except Exception:
                pass
            return []

    def _persist(self, ws, owner, query, seeds, neighborhood, strategy, hops, graph_hits, vector_hits,
                 cache_hit, avg_conf, timings, hybrid) -> None:
        log = SemanticMemoryLog(
            id=f"smem_{uuid.uuid4().hex[:16]}", workspace_id=ws, owner_id=owner, query=query[:4000],
            mode="hybrid" if hybrid else "graph",
            recognized_entities=[{"id": s.id, "name": s.canonical_name} for s in seeds],
            seed_count=len(seeds), traversal_depth=hops, traversal_strategy=strategy,
            neighborhood_size=neighborhood.size, edges_traversed=len(neighborhood.edges),
            hits_returned=graph_hits, graph_hits=graph_hits, vector_hits=vector_hits, cache_hit=cache_hit,
            avg_confidence=avg_conf, recognition_ms=timings["recognition_ms"],
            traversal_ms=timings["traversal_ms"], retrieval_ms=timings["retrieval_ms"],
            fusion_ms=timings["fusion_ms"], context_ms=timings["context_ms"], total_ms=timings["total_ms"])
        self.memory.save_log(log)

    # ------------------------------------------------------------------ persistent-memory views + previews
    def recognize(self, workspace_id: str, owner_id: str, query: str) -> List[Dict[str, Any]]:
        return [{"id": s.id, "canonical_name": s.canonical_name, "entity_type": s.entity_type,
                 "aliases": s.aliases or [], "degree": s.degree, "mention_count": s.mention_count}
                for s in self.recognizer.recognize(query, workspace_id, owner_id, repo=self.graph)]

    def neighborhood(self, workspace_id: str, owner_id: str, entity_id: str, *, hops: int = 1,
                     strategy: str = "bfs", max_nodes: int = 40) -> Dict[str, Any]:
        seed = self.graph.get_entity(entity_id, owner_id)
        if seed is None or seed.workspace_id != workspace_id:
            raise EntityNotFound(entity_id)
        nb = TraversalEngine().expand(self.graph, workspace_id, owner_id, [entity_id], hops=hops,
                                      strategy=strategy, rel_types=None, max_nodes=max_nodes)
        return {"seed": {"id": seed.id, "name": seed.canonical_name},
                "nodes": [{"id": n.id, "name": n.canonical_name, "type": n.entity_type,
                           "hop": nb.hop.get(n.id, 0), "degree": n.degree} for n in nb.nodes.values()],
                "edges": [{"id": e.id, "source": e.source_id, "target": e.target_id, "type": e.rel_type,
                           "weight": e.weight} for e in nb.edges], "truncated": nb.truncated}

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        from app.memory.cache import NEIGHBORHOOD_CACHE as cache
        return {**self.memory.stats(workspace_id), "graph": self.graph.metrics(workspace_id),
                "cache": cache.stats()}

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30):
        return self.memory.logs(workspace_id, owner_id, limit=limit)


class MemorySynchronizer:
    """Keep the graph + memory cache eventually consistent (Step 10)."""

    def __init__(self, db: Session):
        self.db = db

    def sync(self, owner_id: str, workspace_id: str, *, document_id: Optional[str] = None,
             force: bool = False) -> Dict[str, Any]:
        from app.knowledge.repository import GraphRepository as KGRepo
        from app.knowledge.service import KnowledgeGraphService
        svc = KnowledgeGraphService(KGRepo(self.db))
        built = None
        if document_id:
            log = svc.ensure_built(owner_id, workspace_id, document_id, force=force)
            built = log.id if log else None
        invalidated = NEIGHBORHOOD_CACHE.invalidate_workspace(workspace_id)
        return {"synced": True, "document_build": built, "cache_invalidated": invalidated}
