"""Data access for semantic memory — reuses GraphRepository for reads + owns SemanticMemoryLog."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.memory.models import SemanticMemoryLog


class MemoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_log(self, log: SemanticMemoryLog) -> SemanticMemoryLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def logs(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[SemanticMemoryLog]:
        return list(self.db.scalars(select(SemanticMemoryLog).where(
            SemanticMemoryLog.workspace_id == workspace_id, SemanticMemoryLog.owner_id == owner_id)
            .order_by(desc(SemanticMemoryLog.created_at)).limit(limit)))

    def stats(self, workspace_id: str) -> dict:
        base = select(func.count()).select_from(SemanticMemoryLog).where(
            SemanticMemoryLog.workspace_id == workspace_id)
        total = int(self.db.scalar(base) or 0)
        cache_hits = int(self.db.scalar(base.where(SemanticMemoryLog.cache_hit.is_(True))) or 0)
        avg_ms = float(self.db.scalar(select(func.coalesce(func.avg(SemanticMemoryLog.total_ms), 0.0))
                                      .where(SemanticMemoryLog.workspace_id == workspace_id)) or 0.0)
        avg_depth = float(self.db.scalar(select(func.coalesce(func.avg(SemanticMemoryLog.neighborhood_size), 0.0))
                                         .where(SemanticMemoryLog.workspace_id == workspace_id)) or 0.0)
        return {"queries": total, "cache_hits": cache_hits, "avg_total_ms": round(avg_ms, 2),
                "avg_neighborhood_size": round(avg_depth, 2)}
