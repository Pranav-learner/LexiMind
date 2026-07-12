"""Knowledge Graph service — orchestrate build + persist telemetry + expose graph reads.

Coordinates the `GraphBuilder` (compute) over the `GraphStore` (`GraphRepository`) and persists a
`GraphConstructionLog` per build. Build is INCREMENTAL (a document merges into the existing graph) with a
`citations`-style staleness guard (`ensure_built`). Contains no extraction logic — that lives in the
injectable extractors. Exposes entity/relationship search, details, stats, validation, logs, and the
agent-contribution seam (Step 16).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.documents.repository import DocumentRepository
from app.knowledge.builder import GraphBuilder, BuildResult
from app.knowledge.errors import DocumentNotFound, EntityNotFound, GraphLogNotFound
from app.knowledge.models import GraphConstructionLog
from app.knowledge.repository import GraphRepository, new_id
from app.knowledge.sources import TextSource, collect_document_sources
from app.knowledge.validator import GraphValidator


class KnowledgeGraphService:
    def __init__(self, repo: GraphRepository, *, builder: Optional[GraphBuilder] = None):
        self.repo = repo
        self.db: Session = repo.db
        self.builder = builder or GraphBuilder(repo)

    # ------------------------------------------------------------------ build (document / workspace / text)
    def build_document(self, owner_id: str, workspace_id: str, document_id: str, *,
                       log_id: Optional[str] = None) -> GraphConstructionLog:
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise DocumentNotFound(document_id)
        sources = collect_document_sources(self.db, doc)
        return self._run_build(owner_id, workspace_id, sources, scope="document",
                               document_id=document_id, log_id=log_id)

    def build_workspace(self, owner_id: str, workspace_id: str, *,
                        log_id: Optional[str] = None) -> GraphConstructionLog:
        docs, _ = DocumentRepository(self.db).list(owner_id, workspace_id, page_size=1000)
        sources: List[TextSource] = []
        for doc in docs:
            sources.extend(collect_document_sources(self.db, doc))
        return self._run_build(owner_id, workspace_id, sources, scope="workspace",
                               document_id=None, log_id=log_id)

    def build_text(self, owner_id: str, workspace_id: str, text: str, *, source_ref: Optional[Dict] = None,
                   scope: str = "agent") -> GraphConstructionLog:
        """Ad-hoc build from raw text (developer /extract endpoint + agent contribution — Step 16)."""
        ref = source_ref or {"document_id": None, "chunk_id": None, "source_type": "text"}
        return self._run_build(owner_id, workspace_id, [TextSource(text, ref)], scope=scope,
                               document_id=ref.get("document_id"))

    def contribute_from_text(self, owner_id: str, workspace_id: str, text: str, *,
                             source_ref: Optional[Dict] = None) -> Optional[GraphConstructionLog]:
        """Agent-integration seam: an agent's output text contributes entities/edges to the graph.

        Best-effort + reuses the SAME extraction pipeline (no duplicated extraction logic). Callers wrap
        this so a graph hiccup never affects the agent run.
        """
        if not (text or "").strip():
            return None
        return self.build_text(owner_id, workspace_id, text, source_ref=source_ref, scope="agent")

    def _run_build(self, owner_id: str, workspace_id: str, sources: List[TextSource], *, scope: str,
                   document_id: Optional[str], log_id: Optional[str] = None) -> GraphConstructionLog:
        t0 = time.perf_counter()
        result: BuildResult = self.builder.build(workspace_id, owner_id, sources)
        ms = (time.perf_counter() - t0) * 1000
        report = result.report or {}
        log = GraphConstructionLog(
            id=log_id or new_id("gcl"), workspace_id=workspace_id, owner_id=owner_id,
            document_id=document_id, scope=scope, status="completed",
            pipeline_version=self.builder.pipeline_version, sources_processed=result.sources_processed,
            chunks_processed=result.sources_processed, entities_extracted=result.entities_extracted,
            entities_created=result.entities_created, entities_merged=result.entities_merged,
            relationships_extracted=result.relationships_extracted,
            relationships_created=result.relationships_created, duplicates_merged=result.duplicates_merged,
            validation_errors=report.get("error_count", 0), validation_warnings=report.get("warning_count", 0),
            avg_confidence=result.avg_confidence, processing_ms=ms,
            report={"validation": report, "events": result.events})
        return self.repo.save_log(log)

    # ------------------------------------------------------------------ incremental staleness guard
    def ensure_built(self, owner_id: str, workspace_id: str, document_id: str, *,
                     force: bool = False) -> Optional[GraphConstructionLog]:
        """Build the document's graph iff it has no completed build yet (or forced). Incremental."""
        if not force:
            prior = [l for l in self.repo.logs(workspace_id, owner_id, limit=100)
                     if l.document_id == document_id and l.status == "completed"]
            if prior:
                return prior[0]
        return self.build_document(owner_id, workspace_id, document_id)

    # ------------------------------------------------------------------ reads
    def search_entities(self, workspace_id: str, owner_id: str, *, query: Optional[str] = None,
                        entity_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.repo.search_entities(workspace_id, owner_id, query=query, entity_type=entity_type, limit=limit)
        return [self._entity_dict(e) for e in rows]

    def entity_detail(self, entity_id: str, owner_id: str) -> Dict[str, Any]:
        ent = self.repo.get_entity(entity_id, owner_id)
        if ent is None:
            raise EntityNotFound(entity_id)
        rels = self.repo.relationships_for(ent.workspace_id, entity_id)
        by_id = {e.id: e for e in self.repo.workspace_entities(ent.workspace_id, owner_id)}
        return {**self._entity_dict(ent),
                "relationships": [self._rel_dict(r, by_id) for r in rels]}

    def search_relationships(self, workspace_id: str, owner_id: str, *, rel_type: Optional[str] = None,
                             limit: int = 100) -> List[Dict[str, Any]]:
        by_id = {e.id: e for e in self.repo.workspace_entities(workspace_id, owner_id)}
        rows = self.repo.workspace_relationships(workspace_id, owner_id, rel_type=rel_type, limit=limit)
        return [self._rel_dict(r, by_id) for r in rows]

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.metrics(workspace_id)

    def validate(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        entities = self.repo.workspace_entities(workspace_id, owner_id)
        rels = self.repo.workspace_relationships(workspace_id, owner_id, limit=5000)
        return GraphValidator().validate(entities, rels).to_dict()

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[GraphConstructionLog]:
        return self.repo.logs(workspace_id, owner_id, limit=limit)

    def get_log(self, log_id: str, owner_id: str) -> GraphConstructionLog:
        log = self.repo.get_log(log_id, owner_id)
        if log is None:
            raise GraphLogNotFound(log_id)
        return log

    # ------------------------------------------------------------------ serialization
    @staticmethod
    def _entity_dict(e) -> Dict[str, Any]:
        return {"id": e.id, "entity_type": e.entity_type, "canonical_name": e.canonical_name,
                "normalized_name": e.normalized_name, "aliases": e.aliases or [],
                "description": e.description, "confidence": e.confidence, "mention_count": e.mention_count,
                "degree": e.degree, "source_refs": e.source_refs or [], "status": e.status,
                "version": e.version}

    @staticmethod
    def _rel_dict(r, by_id) -> Dict[str, Any]:
        s = by_id.get(r.source_id); t = by_id.get(r.target_id)
        return {"id": r.id, "rel_type": r.rel_type, "directed": r.directed, "weight": r.weight,
                "confidence": r.confidence, "mention_count": r.mention_count,
                "source_id": r.source_id, "target_id": r.target_id,
                "source_name": s.canonical_name if s else None,
                "target_name": t.canonical_name if t else None,
                "evidence": r.evidence or [], "version": r.version}
