"""Knowledge Workspace orchestrator (Phase 7 capstone) — a PURE integration layer.

Coordinates the existing subsystems (Module-1 graph, Module-2 semantic memory, Module-3 reasoning,
ChatService) into ONE knowledge-centric workspace, plus controlled editing + activity logging. It owns
NO graph/retrieval/reasoning/inference logic — every method delegates. Mirrors the Phase-4/5 workspace
capstones (WorkspaceOrchestrator / MediaWorkspaceOrchestrator).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.models import GraphRelationship
from app.knowledge.repository import GraphRepository
from app.knowledgeworkspace.analytics import graph_analytics
from app.knowledgeworkspace.editing import GraphEditor
from app.knowledgeworkspace.errors import EntityNotFound, RelationshipNotFound
from app.knowledgeworkspace.repository import WorkspaceLogRepository
from app.knowledgeworkspace.timeline import knowledge_timeline


class KnowledgeWorkspaceOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.graph = GraphRepository(db)
        self.log = WorkspaceLogRepository(db)

    # ------------------------------------------------------------------ overview
    def overview(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        m = self.graph.metrics(workspace_id)
        top = sorted(self.graph.search_entities(workspace_id, owner_id, limit=8),
                     key=lambda e: e.degree, reverse=True)
        return {"workspace_id": workspace_id, "entities": m["entities"], "relationships": m["relationships"],
                "density": m["density"], "entity_types": m["entity_types"],
                "top_concepts": [{"id": e.id, "name": e.canonical_name, "type": e.entity_type,
                                  "degree": e.degree} for e in top],
                "activity": self.log.activity_counts(workspace_id)}

    # ------------------------------------------------------------------ graph explorer (lazy)
    def graph_view(self, workspace_id: str, owner_id: str, *, seed: Optional[str] = None, hops: int = 1,
                   limit: int = 40) -> Dict[str, Any]:
        if seed:
            from app.memory.service import SemanticMemoryService
            nb = SemanticMemoryService(self.db).neighborhood(workspace_id, owner_id, seed, hops=hops,
                                                             max_nodes=limit)
            node_ids = {n["id"] for n in nb["nodes"]}
            nodes = nb["nodes"]
            edges = nb["edges"]
            self.log.record(workspace_id, owner_id, "entity_expansion", target_id=seed,
                            detail={"hops": hops, "nodes": len(nodes)})
        else:
            # initial view: the most-connected concepts + edges among them (never the whole graph)
            top = sorted(self.graph.search_entities(workspace_id, owner_id, limit=limit),
                         key=lambda e: e.degree, reverse=True)[:limit]
            by_id = {e.id: e for e in top}
            node_ids = set(by_id)
            nodes = [{"id": e.id, "name": e.canonical_name, "type": e.entity_type, "degree": e.degree}
                     for e in top]
            all_edges = self.graph.workspace_relationships(workspace_id, owner_id, active_only=False, limit=2000)
            edges = [{"id": r.id, "source": r.source_id, "target": r.target_id, "type": r.rel_type,
                      "weight": r.weight, "status": r.status}
                     for r in all_edges if r.source_id in node_ids and r.target_id in node_ids
                     and r.status in ("active", "inferred")]
            self.log.record(workspace_id, owner_id, "graph_search", detail={"nodes": len(nodes)})
        return {"seed": seed, "nodes": nodes, "edges": edges, "node_count": len(nodes),
                "edge_count": len(edges)}

    # ------------------------------------------------------------------ entity / relationship detail
    def entity_detail(self, workspace_id: str, owner_id: str, entity_id: str) -> Dict[str, Any]:
        from app.knowledge.service import KnowledgeGraphService
        try:
            detail = KnowledgeGraphService(self.graph).entity_detail(entity_id, owner_id)
        except Exception:
            raise EntityNotFound(entity_id)
        # reasoning summary (Module 3) — why this entity matters + its dependencies
        try:
            from app.graphreason.service import GraphReasoningService
            dep = GraphReasoningService(self.db).dependency_analysis(workspace_id, owner_id, entity_id, hops=3)
            detail["reasoning"] = {"dependencies": dep["dependencies"][:6], "root_causes": dep["root_causes"]}
        except Exception:
            detail["reasoning"] = {}
        self.log.record(workspace_id, owner_id, "node_view", target_id=entity_id)
        return detail

    def relationship_detail(self, workspace_id: str, owner_id: str, rel_id: str) -> Dict[str, Any]:
        r = self.db.scalar(select(GraphRelationship).where(
            GraphRelationship.id == rel_id, GraphRelationship.owner_id == owner_id))
        if r is None:
            raise RelationshipNotFound(rel_id)
        by_id = {e.id: e for e in self.graph.workspace_entities(workspace_id, owner_id)}
        s = by_id.get(r.source_id); t = by_id.get(r.target_id)
        # "why connected" — reasoning paths between the two endpoints
        why: List[Any] = []
        try:
            from app.graphreason.engine import GraphReasoner
            from app.graphreason.paths import PathReasoner, build_adjacency
            ents = {e.id: e for e in self.graph.workspace_entities(workspace_id, owner_id)}
            edges = self.graph.workspace_relationships(workspace_id, owner_id, limit=5000)
            adj = build_adjacency(edges, ents, directed=False)
            paths = PathReasoner().find_paths(adj, ents, [r.source_id], hops=3, targets=[r.target_id],
                                              max_paths=5)
            why = [p.to_dict() for p in paths]
        except Exception:
            pass
        self.log.record(workspace_id, owner_id, "relationship_view", target_id=rel_id)
        return {"id": r.id, "rel_type": r.rel_type, "directed": r.directed, "weight": r.weight,
                "confidence": r.confidence, "status": r.status, "version": r.version,
                "inferred": r.status == "inferred", "evidence": r.evidence or [],
                "source": {"id": r.source_id, "name": s.canonical_name if s else None},
                "target": {"id": r.target_id, "name": t.canonical_name if t else None},
                "why_connected": why}

    # ------------------------------------------------------------------ unified search
    def search(self, workspace_id: str, owner_id: str, *, query: str, hybrid: bool = False) -> Dict[str, Any]:
        from app.memory.service import SemanticMemoryService
        res = SemanticMemoryService(self.db).retrieve(workspace_id, owner_id, query=query, hops=2, limit=20,
                                                      hybrid=hybrid)
        # unified: recognized query entities (Module-2) ⊕ entity-name matches (Module-1), deduped
        entities: List[Dict[str, Any]] = []
        seen = set()
        for s in res["recognized_entities"]:
            seen.add(s["id"]); entities.append({"id": s["id"], "name": s["name"], "type": s["type"]})
        for e in self.graph.search_entities(workspace_id, owner_id, query=query, limit=10):
            if e.id not in seen:
                seen.add(e.id)
                entities.append({"id": e.id, "name": e.canonical_name, "type": e.entity_type})
        self.log.record(workspace_id, owner_id, "graph_search", detail={"query": query[:200]})
        return {"query": query, "entities": entities, "hits": res["hits"], "context_text": res["context_text"],
                "citations": res["citations"], "fused": res["fused"], "mode": res["mode"]}

    # ------------------------------------------------------------------ timeline / analytics
    def timeline(self, workspace_id: str, owner_id: str, *, limit: int = 60) -> List[Dict[str, Any]]:
        self.log.record(workspace_id, owner_id, "timeline_view")
        return knowledge_timeline(self.db, workspace_id, owner_id, limit=limit)

    def analytics(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        self.log.record(workspace_id, owner_id, "analytics_view")
        return graph_analytics(self.db, workspace_id, owner_id)

    def activity(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        return [{"id": l.id, "activity_type": l.activity_type, "target_id": l.target_id,
                 "detail": l.detail, "created_at": l.created_at.isoformat() if l.created_at else None}
                for l in self.log.recent(workspace_id, owner_id, limit=limit)]

    # ------------------------------------------------------------------ AI graph chat (reuse ChatService)
    def graph_chat(self, owner_id: str, workspace_id: str, *, content: str, engine,
                   conversation_id: Optional[str] = None, top_k: int = 12) -> Dict[str, Any]:
        from app.chat.repository import ConversationRepository, MessageRepository
        from app.chat.service import ChatService
        from app.workspaces.repository import WorkspaceRepository
        from app.workspaces.service import WorkspaceService
        chat = ChatService(ConversationRepository(self.db), MessageRepository(self.db),
                           WorkspaceService(WorkspaceRepository(self.db)))
        # run_message fetches (and 404s on) the conversation itself; only create a fresh one when needed
        cid = conversation_id or chat.create(owner_id, workspace_id, title="Graph Chat").id
        user = assistant = None
        citations: List[Dict[str, Any]] = []
        for ev in chat.run_message(cid, owner_id, content, engine, top_k=top_k):
            if ev["type"] == "user":
                user = ev["message"]
            elif ev["type"] == "done":
                assistant = ev["message"]; citations = ev.get("citations", [])
            elif ev["type"] == "error":
                assistant = ev.get("message")
        self.log.record(workspace_id, owner_id, "graph_chat", target_id=cid,
                        detail={"question": content[:200]})
        return {"conversation_id": cid,
                "answer": getattr(assistant, "content", "") if assistant else "",
                "citations": [self._cit(c) for c in citations],
                "grounded": engine.last_result.get("grounded", False)}

    @staticmethod
    def _cit(c) -> Dict[str, Any]:
        return {"document_id": getattr(c, "document_id", None), "text": getattr(c, "text", "")[:300],
                "source": getattr(c, "source", None), "confidence": getattr(c, "confidence", None)}

    # ------------------------------------------------------------------ controlled editing
    def edit(self, workspace_id: str, owner_id: str, *, op: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ed = GraphEditor(self.db)
        result: Dict[str, Any]
        if op == "rename_entity":
            e = ed.rename_entity(params["entity_id"], owner_id, new_name=params["new_name"])
            result = {"entity": self._ent(e)}
        elif op == "edit_metadata":
            e = ed.edit_metadata(params["entity_id"], owner_id, description=params.get("description"),
                                 entity_type=params.get("entity_type"), aliases=params.get("aliases"))
            result = {"entity": self._ent(e)}
        elif op == "merge_entities":
            e = ed.merge_entities(params["source_id"], params["target_id"], owner_id)
            result = {"entity": self._ent(e)}
        elif op == "split_entity":
            e = ed.split_entity(params["entity_id"], owner_id, new_name=params["new_name"],
                                move_aliases=params.get("move_aliases"))
            result = {"entity": self._ent(e)}
        elif op == "delete_entity":
            e = ed.delete_entity(params["entity_id"], owner_id)
            result = {"entity": self._ent(e)}
        elif op == "create_relationship":
            r = ed.create_relationship(workspace_id, owner_id, source_id=params["source_id"],
                                       target_id=params["target_id"], rel_type=params["rel_type"])
            result = {"relationship_id": r.id, "status": r.status}
        elif op == "delete_relationship":
            r = ed.delete_relationship(params["rel_id"], owner_id)
            result = {"relationship_id": r.id, "status": r.status}
        elif op in ("approve_relationship", "reject_relationship"):
            r = ed.review_inferred(params["rel_id"], owner_id, approve=(op == "approve_relationship"))
            result = {"relationship_id": r.id, "status": r.status}
        else:
            from app.knowledgeworkspace.errors import InvalidEdit
            raise InvalidEdit(f"Unknown edit operation '{op}'.")
        self.log.record(workspace_id, owner_id, "graph_edit", detail={"op": op, **result})
        return {"op": op, **result}

    @staticmethod
    def _ent(e) -> Dict[str, Any]:
        return {"id": e.id, "canonical_name": e.canonical_name, "entity_type": e.entity_type,
                "aliases": e.aliases or [], "status": e.status, "version": e.version,
                "merged_into": e.merged_into}
