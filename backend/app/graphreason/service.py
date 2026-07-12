"""Graph Reasoning service — orchestrate reasoning + persist telemetry/inferences + expose reads.

Thin coordination over the `GraphReasoner` (compute) and the repository (log + inferred edges). Reuses
Module-1 graph, Module-2 recognition, and the Phase-6 Verification Engine — no reasoning/verification/
retrieval logic is duplicated. Exposes reason / preview / dependency / root-cause / explain / logs / stats.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.graphreason.engine import GraphReasoner
from app.graphreason.errors import EntityNotFound, ReasoningLogNotFound
from app.graphreason.models import GraphReasoningLog
from app.graphreason.repository import ReasoningRepository
from app.knowledge.repository import GraphRepository


class GraphReasoningService:
    def __init__(self, db: Session, *, reasoner: Optional[GraphReasoner] = None):
        self.db = db
        self.repo = ReasoningRepository(db)
        self.reasoner = reasoner or GraphReasoner(db)

    # ------------------------------------------------------------------ reason
    def reason(self, workspace_id: str, owner_id: str, *, query: str, hops: int = 3, directed: bool = False,
               verify: bool = True, dependency: bool = False, persist: bool = True,
               persist_inferences: bool = True, seed_entity_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        result = self.reasoner.reason(workspace_id, owner_id, query=query, hops=hops, directed=directed,
                                      verify=verify, dependency=dependency, seed_entity_ids=seed_entity_ids)
        if persist_inferences and result.inferences and not result.cache_hit:
            try:
                self.repo.persist_inferences(workspace_id, owner_id, result.inferences)
            except Exception:
                self.db.rollback()
        if persist:
            self._persist(workspace_id, owner_id, result)
        return result.to_dict()

    def preview(self, workspace_id: str, owner_id: str, *, query: str, hops: int = 2) -> Dict[str, Any]:
        result = self.reasoner.reason(workspace_id, owner_id, query=query, hops=hops, verify=False,
                                      use_cache=False)
        return {"query": query, "seeds": result.seeds, "paths": [p.to_dict() for p in result.paths[:10]],
                "inferences": [r.to_dict() for r in result.inferences[:10]], "complexity": result.complexity}

    def dependency_analysis(self, workspace_id: str, owner_id: str, entity_id: str, *,
                            hops: int = 5) -> Dict[str, Any]:
        seed = self.graph_repo().get_entity(entity_id, owner_id)
        if seed is None or seed.workspace_id != workspace_id:
            raise EntityNotFound(entity_id)
        result = self.reasoner.reason(workspace_id, owner_id, query=seed.canonical_name, hops=hops,
                                      directed=True, verify=False, dependency=True,
                                      seed_entity_ids=[entity_id], use_cache=False)
        return {"entity": {"id": seed.id, "name": seed.canonical_name},
                "dependencies": [d.to_dict() for d in result.dependencies],
                "root_causes": result.root_causes}

    def root_cause(self, workspace_id: str, owner_id: str, *, query: str) -> Dict[str, Any]:
        result = self.reasoner.reason(workspace_id, owner_id, query=query, hops=5, directed=True,
                                      verify=False, dependency=True, use_cache=False)
        return {"query": query, "seeds": result.seeds, "root_causes": result.root_causes,
                "dependencies": [d.to_dict() for d in result.dependencies[:10]]}

    def explain(self, workspace_id: str, owner_id: str, *, query: str, hops: int = 3) -> Dict[str, Any]:
        result = self.reasoner.reason(workspace_id, owner_id, query=query, hops=hops, verify=True,
                                      use_cache=False)
        return {"query": query, "explanation": result.explanation,
                "confidence": result.confidence.to_dict() if result.confidence else None}

    # ------------------------------------------------------------------ persistence + reads
    def _persist(self, workspace_id: str, owner_id: str, result) -> None:
        conf = result.confidence
        log = GraphReasoningLog(
            id=f"gr_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            query=result.query[:4000], pipeline_version=self.reasoner.pipeline_version,
            seed_count=len(result.seeds), traversal_depth=result.complexity.get("max_depth", 0),
            relationships_traversed=result.complexity.get("edges", 0), paths_found=len(result.paths),
            inference_count=len(result.inferences), dependency_chains=len(result.dependencies),
            root_causes=len(result.root_causes),
            reasoning_complexity=result.complexity.get("nodes", 0) + result.complexity.get("edges", 0),
            cache_hit=result.cache_hit, overall_confidence=(conf.overall if conf else 0.0),
            confidence_band=(conf.breakdown.band if conf else "low"),
            verification_status=(result.verification or {}).get("status", "not_run"),
            recognition_ms=result.timings.get("recognition_ms", 0.0),
            paths_ms=result.timings.get("paths_ms", 0.0), inference_ms=result.timings.get("inference_ms", 0.0),
            verification_ms=result.timings.get("verification_ms", 0.0),
            confidence_ms=result.timings.get("confidence_ms", 0.0), total_ms=result.timings.get("total_ms", 0.0),
            report={"explanation": result.explanation, "complexity": result.complexity})
        self.repo.save_log(log)

    def graph_repo(self) -> GraphRepository:
        return GraphRepository(self.db)

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30):
        return self.repo.logs(workspace_id, owner_id, limit=limit)

    def get_log(self, log_id: str, owner_id: str):
        log = self.repo.get_log(log_id, owner_id)
        if log is None:
            raise ReasoningLogNotFound(log_id)
        return log

    def inferred(self, workspace_id: str, owner_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        by_id = {e.id: e for e in self.graph_repo().workspace_entities(workspace_id, owner_id)}
        out = []
        for r in self.repo.list_inferred(workspace_id, owner_id, limit=limit):
            s = by_id.get(r.source_id); t = by_id.get(r.target_id)
            out.append({"id": r.id, "rel_type": r.rel_type, "confidence": r.confidence,
                        "source_name": s.canonical_name if s else None,
                        "target_name": t.canonical_name if t else None,
                        "derivation": (r.evidence or [{}])[0].get("derivation"), "status": r.status})
        return out

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        from app.graphreason.cache import REASONING_CACHE
        return {**self.repo.stats(workspace_id), "cache": REASONING_CACHE.stats()}
