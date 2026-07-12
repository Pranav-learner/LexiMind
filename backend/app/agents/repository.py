"""Agent data access — ONLY the execution-telemetry table."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentExecutionLog


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, log: AgentExecutionLog) -> AgentExecutionLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get(self, execution_id: str, owner_id: str) -> Optional[AgentExecutionLog]:
        return self.db.scalar(select(AgentExecutionLog).where(
            AgentExecutionLog.id == execution_id, AgentExecutionLog.owner_id == owner_id))

    def list(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[AgentExecutionLog]:
        return list(self.db.scalars(
            select(AgentExecutionLog).where(
                AgentExecutionLog.workspace_id == workspace_id, AgentExecutionLog.owner_id == owner_id)
            .order_by(desc(AgentExecutionLog.created_at)).limit(limit)))

    def stats(self, workspace_id: str) -> dict:
        total = int(self.db.scalar(select(func.count()).select_from(AgentExecutionLog)
                                   .where(AgentExecutionLog.workspace_id == workspace_id)) or 0)
        ok = int(self.db.scalar(select(func.count()).select_from(AgentExecutionLog).where(
            AgentExecutionLog.workspace_id == workspace_id, AgentExecutionLog.success.is_(True))) or 0)
        avg = float(self.db.scalar(select(func.coalesce(func.avg(AgentExecutionLog.total_ms), 0.0))
                                   .where(AgentExecutionLog.workspace_id == workspace_id)) or 0.0)
        return {"executions": total, "successful": ok, "avg_total_ms": round(avg, 2)}
