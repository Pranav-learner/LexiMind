"""Data access for optimization — run logs + per-workspace policy."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.optimization.models import OptimizationRunLog, WorkspacePolicy


class OptimizationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ run logs
    def save_run(self, run: OptimizationRunLog) -> OptimizationRunLog:
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def runs(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[OptimizationRunLog]:
        return list(self.db.scalars(select(OptimizationRunLog).where(
            OptimizationRunLog.workspace_id == workspace_id, OptimizationRunLog.owner_id == owner_id)
            .order_by(desc(OptimizationRunLog.created_at)).limit(limit)))

    # ------------------------------------------------------------------ workspace policy
    def get_policy(self, workspace_id: str, owner_id: str) -> Optional[WorkspacePolicy]:
        return self.db.scalar(select(WorkspacePolicy).where(
            WorkspacePolicy.workspace_id == workspace_id, WorkspacePolicy.owner_id == owner_id))

    def set_policy(self, workspace_id: str, owner_id: str, policy: str) -> WorkspacePolicy:
        row = self.get_policy(workspace_id, owner_id)
        if row is None:
            row = WorkspacePolicy(workspace_id=workspace_id, owner_id=owner_id, policy=policy)
            self.db.add(row)
        else:
            row.policy = policy
        self.db.commit()
        self.db.refresh(row)
        return row
