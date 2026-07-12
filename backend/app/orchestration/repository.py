"""Data access for the orchestration telemetry table (OrchestrationExecutionLog only)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.orchestration.models import OrchestrationExecutionLog


class OrchestrationRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, log: OrchestrationExecutionLog) -> OrchestrationExecutionLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get(self, orchestration_id: str, owner_id: str) -> Optional[OrchestrationExecutionLog]:
        return self.db.scalar(select(OrchestrationExecutionLog).where(
            OrchestrationExecutionLog.id == orchestration_id,
            OrchestrationExecutionLog.owner_id == owner_id))

    def list(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[OrchestrationExecutionLog]:
        return list(self.db.scalars(
            select(OrchestrationExecutionLog).where(
                OrchestrationExecutionLog.workspace_id == workspace_id,
                OrchestrationExecutionLog.owner_id == owner_id)
            .order_by(desc(OrchestrationExecutionLog.created_at)).limit(limit)))

    def stats(self, workspace_id: str) -> dict:
        base = select(func.count()).select_from(OrchestrationExecutionLog).where(
            OrchestrationExecutionLog.workspace_id == workspace_id)
        total = int(self.db.scalar(base) or 0)
        completed = int(self.db.scalar(base.where(OrchestrationExecutionLog.status == "completed")) or 0)
        avg = float(self.db.scalar(
            select(func.coalesce(func.avg(OrchestrationExecutionLog.total_ms), 0.0))
            .where(OrchestrationExecutionLog.workspace_id == workspace_id)) or 0.0)
        return {"orchestrations": total, "completed": completed, "avg_total_ms": round(avg, 2)}
