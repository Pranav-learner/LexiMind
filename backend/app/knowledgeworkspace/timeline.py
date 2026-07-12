"""Knowledge Timeline (Step 9) — READ-ONLY chronology of how the graph evolved.

Merges entity/relationship creation, graph builds, and agent contributions (from the construction logs)
into a single time-ordered stream so users see knowledge GROW. Pure aggregation over existing tables —
no new persistence.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.models import GraphConstructionLog, GraphEntity, GraphRelationship


def knowledge_timeline(db: Session, workspace_id: str, owner_id: str, *, limit: int = 60) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []

    ents = db.scalars(select(GraphEntity).where(
        GraphEntity.workspace_id == workspace_id, GraphEntity.owner_id == owner_id)
        .order_by(GraphEntity.created_at.desc()).limit(limit)).all()
    for e in ents:
        events.append({"type": "entity_created", "at": e.created_at.isoformat() if e.created_at else None,
                       "entity_id": e.id, "name": e.canonical_name, "entity_type": e.entity_type,
                       "version": e.version, "status": e.status})

    rels = db.scalars(select(GraphRelationship).where(
        GraphRelationship.workspace_id == workspace_id, GraphRelationship.owner_id == owner_id)
        .order_by(GraphRelationship.created_at.desc()).limit(limit)).all()
    for r in rels:
        events.append({"type": "relationship_inferred" if r.status == "inferred" else "relationship_created",
                       "at": r.created_at.isoformat() if r.created_at else None, "rel_id": r.id,
                       "rel_type": r.rel_type, "status": r.status})

    logs = db.scalars(select(GraphConstructionLog).where(
        GraphConstructionLog.workspace_id == workspace_id, GraphConstructionLog.owner_id == owner_id)
        .order_by(GraphConstructionLog.created_at.desc()).limit(limit)).all()
    for l in logs:
        events.append({"type": "agent_contribution" if l.scope == "agent" else "graph_build",
                       "at": l.created_at.isoformat() if l.created_at else None, "scope": l.scope,
                       "entities_created": l.entities_created, "entities_merged": l.entities_merged,
                       "relationships_created": l.relationships_created})

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:limit]
