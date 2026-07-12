"""Graph Analytics (Step 10) — READ-ONLY aggregation over existing observability + graph tables.

Reuses the Module-1 graph metrics + construction logs, the Module-3 reasoning logs, and the workspace
activity log — it never recomputes what those already own. Produces the knowledge-distribution + growth
+ top-concepts + reasoning + agent-contribution stats the workspace dashboard renders.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge.models import GraphConstructionLog, GraphEntity, GraphRelationship
from app.knowledge.repository import GraphRepository


def graph_analytics(db: Session, workspace_id: str, owner_id: str) -> Dict[str, Any]:
    repo = GraphRepository(db)
    metrics = repo.metrics(workspace_id)   # entities/relationships/merged/type distributions/density

    # top connected concepts (by cached degree)
    top = repo.search_entities(workspace_id, owner_id, limit=10)
    top_connected = [{"id": e.id, "name": e.canonical_name, "type": e.entity_type, "degree": e.degree,
                      "mentions": e.mention_count} for e in sorted(top, key=lambda x: x.degree, reverse=True)]

    # most referenced (by mention_count)
    most_ref_rows = db.scalars(select(GraphEntity).where(
        GraphEntity.workspace_id == workspace_id, GraphEntity.status == "active")
        .order_by(GraphEntity.mention_count.desc()).limit(10)).all()
    most_referenced = [{"id": e.id, "name": e.canonical_name, "mentions": e.mention_count}
                       for e in most_ref_rows]

    # inferred vs explicit relationships
    inferred = int(db.scalar(select(func.count()).select_from(GraphRelationship).where(
        GraphRelationship.workspace_id == workspace_id, GraphRelationship.status == "inferred")) or 0)

    # knowledge growth + agent contributions (from construction logs)
    builds = int(db.scalar(select(func.count()).select_from(GraphConstructionLog).where(
        GraphConstructionLog.workspace_id == workspace_id)) or 0)
    agent_contrib = int(db.scalar(select(func.count()).select_from(GraphConstructionLog).where(
        GraphConstructionLog.workspace_id == workspace_id, GraphConstructionLog.scope == "agent")) or 0)
    entities_created = int(db.scalar(select(func.coalesce(func.sum(GraphConstructionLog.entities_created), 0))
                                     .where(GraphConstructionLog.workspace_id == workspace_id)) or 0)

    # reasoning stats (reuse the reasoning repository)
    try:
        from app.graphreason.repository import ReasoningRepository
        reasoning = ReasoningRepository(db).stats(workspace_id)
    except Exception:
        reasoning = {}

    return {
        "entities": metrics["entities"], "relationships": metrics["relationships"],
        "merged_entities": metrics["merged_entities"], "inferred_relationships": inferred,
        "density": metrics["density"], "entity_types": metrics["entity_types"],
        "relationship_types": metrics["relationship_types"],
        "top_connected": top_connected, "most_referenced": most_referenced,
        "growth": {"builds": builds, "entities_created": entities_created, "agent_contributions": agent_contrib},
        "reasoning": reasoning,
    }
