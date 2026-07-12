"""SQL graph store (Step 8 implementation) — satisfies the `GraphStore` Protocol over SQLAlchemy.

All graph SQL lives here (workspace + owner scoped, soft-delete aware). A future Neo4j/AGE backend
implements the same method surface; nothing above the interface changes.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.knowledge.models import GraphConstructionLog, GraphEntity, GraphRelationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class GraphRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ entities
    def workspace_entities(self, workspace_id: str, owner_id: str, *, active_only: bool = True) -> List[GraphEntity]:
        stmt = select(GraphEntity).where(GraphEntity.workspace_id == workspace_id,
                                         GraphEntity.owner_id == owner_id)
        if active_only:
            stmt = stmt.where(GraphEntity.status == "active")
        return list(self.db.scalars(stmt))

    def add_entity(self, entity: GraphEntity) -> GraphEntity:
        self.db.add(entity)
        self.db.flush()
        return entity

    def update_entity(self, entity: GraphEntity) -> GraphEntity:
        self.db.add(entity)
        self.db.flush()
        return entity

    def get_entity(self, entity_id: str, owner_id: str) -> Optional[GraphEntity]:
        return self.db.scalar(select(GraphEntity).where(
            GraphEntity.id == entity_id, GraphEntity.owner_id == owner_id))

    def search_entities(self, workspace_id: str, owner_id: str, *, query: Optional[str] = None,
                        entity_type: Optional[str] = None, limit: int = 50) -> List[GraphEntity]:
        stmt = select(GraphEntity).where(GraphEntity.workspace_id == workspace_id,
                                         GraphEntity.owner_id == owner_id, GraphEntity.status == "active")
        if entity_type:
            stmt = stmt.where(GraphEntity.entity_type == entity_type)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(or_(func.lower(GraphEntity.canonical_name).like(like),
                                  GraphEntity.normalized_name.like(f"%{query.lower().replace(' ', '')}%")))
        return list(self.db.scalars(stmt.order_by(desc(GraphEntity.degree), desc(GraphEntity.mention_count)).limit(limit)))

    # ------------------------------------------------------------------ relationships
    def add_relationship(self, rel: GraphRelationship) -> GraphRelationship:
        self.db.add(rel)
        self.db.flush()
        return rel

    def update_relationship(self, rel: GraphRelationship) -> GraphRelationship:
        self.db.add(rel)
        self.db.flush()
        return rel

    def find_relationship(self, workspace_id: str, source_id: str, target_id: str,
                          rel_type: str) -> Optional[GraphRelationship]:
        return self.db.scalar(select(GraphRelationship).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.source_id == source_id,
            GraphRelationship.target_id == target_id, GraphRelationship.rel_type == rel_type,
            GraphRelationship.status == "active"))

    def relationships_for(self, workspace_id: str, entity_id: str) -> List[GraphRelationship]:
        return list(self.db.scalars(select(GraphRelationship).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.status == "active",
            or_(GraphRelationship.source_id == entity_id, GraphRelationship.target_id == entity_id))))

    def workspace_relationships(self, workspace_id: str, owner_id: str, *, active_only: bool = True,
                                rel_type: Optional[str] = None, limit: int = 500) -> List[GraphRelationship]:
        stmt = select(GraphRelationship).where(GraphRelationship.workspace_id == workspace_id,
                                               GraphRelationship.owner_id == owner_id)
        if active_only:
            stmt = stmt.where(GraphRelationship.status == "active")
        if rel_type:
            stmt = stmt.where(GraphRelationship.rel_type == rel_type)
        return list(self.db.scalars(stmt.order_by(desc(GraphRelationship.weight)).limit(limit)))

    # ------------------------------------------------------------------ telemetry / metrics
    def save_log(self, log: GraphConstructionLog) -> GraphConstructionLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get_log(self, log_id: str, owner_id: str) -> Optional[GraphConstructionLog]:
        return self.db.scalar(select(GraphConstructionLog).where(
            GraphConstructionLog.id == log_id, GraphConstructionLog.owner_id == owner_id))

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[GraphConstructionLog]:
        return list(self.db.scalars(select(GraphConstructionLog).where(
            GraphConstructionLog.workspace_id == workspace_id, GraphConstructionLog.owner_id == owner_id)
            .order_by(desc(GraphConstructionLog.created_at)).limit(limit)))

    def entity_count(self, workspace_id: str, owner_id: str) -> int:
        return int(self.db.scalar(select(func.count()).select_from(GraphEntity).where(
            GraphEntity.workspace_id == workspace_id, GraphEntity.owner_id == owner_id,
            GraphEntity.status == "active")) or 0)

    def metrics(self, workspace_id: str) -> Dict[str, Any]:
        ents = int(self.db.scalar(select(func.count()).select_from(GraphEntity).where(
            GraphEntity.workspace_id == workspace_id, GraphEntity.status == "active")) or 0)
        rels = int(self.db.scalar(select(func.count()).select_from(GraphRelationship).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.status == "active")) or 0)
        by_type_rows = self.db.execute(select(GraphEntity.entity_type, func.count()).where(
            GraphEntity.workspace_id == workspace_id, GraphEntity.status == "active")
            .group_by(GraphEntity.entity_type)).all()
        by_rel_rows = self.db.execute(select(GraphRelationship.rel_type, func.count()).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.status == "active")
            .group_by(GraphRelationship.rel_type)).all()
        merged = int(self.db.scalar(select(func.count()).select_from(GraphEntity).where(
            GraphEntity.workspace_id == workspace_id, GraphEntity.status == "merged")) or 0)
        return {"entities": ents, "relationships": rels, "merged_entities": merged,
                "entity_types": {t: n for t, n in by_type_rows},
                "relationship_types": {t: n for t, n in by_rel_rows},
                "density": round(rels / ents, 3) if ents else 0.0}

    def commit(self) -> None:
        self.db.commit()
