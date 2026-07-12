"""Data access for the specialized-agent task log (AgentTaskLog only)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentTaskLog


class AgentTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, log: AgentTaskLog) -> AgentTaskLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get(self, task_id: str, owner_id: str) -> Optional[AgentTaskLog]:
        return self.db.scalar(select(AgentTaskLog).where(
            AgentTaskLog.id == task_id, AgentTaskLog.owner_id == owner_id))

    def list(self, workspace_id: str, owner_id: str, *, limit: int = 30,
             task_type: Optional[str] = None) -> List[AgentTaskLog]:
        stmt = select(AgentTaskLog).where(
            AgentTaskLog.workspace_id == workspace_id, AgentTaskLog.owner_id == owner_id)
        if task_type:
            stmt = stmt.where(AgentTaskLog.task_type == task_type)
        return list(self.db.scalars(stmt.order_by(desc(AgentTaskLog.created_at)).limit(limit)))

    def stats(self, workspace_id: str) -> dict:
        base = select(func.count()).select_from(AgentTaskLog).where(AgentTaskLog.workspace_id == workspace_id)
        total = int(self.db.scalar(base) or 0)
        ok = int(self.db.scalar(base.where(AgentTaskLog.success.is_(True))) or 0)
        avg = float(self.db.scalar(select(func.coalesce(func.avg(AgentTaskLog.total_ms), 0.0))
                                   .where(AgentTaskLog.workspace_id == workspace_id)) or 0.0)
        tokens = int(self.db.scalar(select(func.coalesce(func.sum(AgentTaskLog.token_usage), 0))
                                    .where(AgentTaskLog.workspace_id == workspace_id)) or 0)
        return {"tasks": total, "successful": ok, "avg_total_ms": round(avg, 2), "total_tokens": tokens}
