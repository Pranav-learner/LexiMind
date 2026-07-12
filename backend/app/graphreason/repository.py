"""Data access for graph reasoning — reasoning log + inferred-edge persistence.

Inferred relationships are stored as `GraphRelationship` rows with `status="inferred"` so they stay
SEPARATE from extracted edges and invisible to retrieval (which reads `active_only`). Idempotent by
(source, target, rel_type, status=inferred).
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.graphreason.models import GraphReasoningLog
from app.knowledge.models import GraphRelationship


class ReasoningRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_log(self, log: GraphReasoningLog) -> GraphReasoningLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[GraphReasoningLog]:
        return list(self.db.scalars(select(GraphReasoningLog).where(
            GraphReasoningLog.workspace_id == workspace_id, GraphReasoningLog.owner_id == owner_id)
            .order_by(desc(GraphReasoningLog.created_at)).limit(limit)))

    def get_log(self, log_id: str, owner_id: str) -> Optional[GraphReasoningLog]:
        return self.db.scalar(select(GraphReasoningLog).where(
            GraphReasoningLog.id == log_id, GraphReasoningLog.owner_id == owner_id))

    def stats(self, workspace_id: str) -> dict:
        base = select(func.count()).select_from(GraphReasoningLog).where(
            GraphReasoningLog.workspace_id == workspace_id)
        total = int(self.db.scalar(base) or 0)
        cache = int(self.db.scalar(base.where(GraphReasoningLog.cache_hit.is_(True))) or 0)
        avg_ms = float(self.db.scalar(select(func.coalesce(func.avg(GraphReasoningLog.total_ms), 0.0))
                                      .where(GraphReasoningLog.workspace_id == workspace_id)) or 0.0)
        inferred = int(self.db.scalar(select(func.count()).select_from(GraphRelationship).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.status == "inferred")) or 0)
        return {"reasonings": total, "cache_hits": cache, "avg_total_ms": round(avg_ms, 2),
                "inferred_relationships": inferred}

    # ------------------------------------------------------------------ inferred edges (status="inferred")
    def persist_inferences(self, workspace_id: str, owner_id: str, inferences) -> int:
        created = 0
        for r in inferences:
            existing = self.db.scalar(select(GraphRelationship).where(
                GraphRelationship.workspace_id == workspace_id, GraphRelationship.source_id == r.source_id,
                GraphRelationship.target_id == r.target_id, GraphRelationship.rel_type == r.rel_type,
                GraphRelationship.status == "inferred"))
            if existing is not None:
                if r.confidence > existing.confidence:
                    existing.confidence = round(r.confidence, 4); existing.version += 1
                continue
            self.db.add(GraphRelationship(
                id=f"rel_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                source_id=r.source_id, target_id=r.target_id, rel_type=r.rel_type, directed=True,
                weight=round(r.confidence, 4), confidence=round(r.confidence, 4), mention_count=1,
                evidence=[{"inferred": True, "derivation": r.derivation, "hops": r.hops}],
                status="inferred", version=1))
            created += 1
        self.db.commit()
        return created

    def list_inferred(self, workspace_id: str, owner_id: str, *, limit: int = 100) -> List[GraphRelationship]:
        return list(self.db.scalars(select(GraphRelationship).where(
            GraphRelationship.workspace_id == workspace_id, GraphRelationship.owner_id == owner_id,
            GraphRelationship.status == "inferred").order_by(desc(GraphRelationship.confidence)).limit(limit)))
