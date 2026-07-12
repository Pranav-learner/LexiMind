"""Data access for the knowledge-workspace activity log."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.knowledgeworkspace.models import KnowledgeWorkspaceLog


class WorkspaceLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def record(self, workspace_id: str, owner_id: str, activity_type: str, *,
               target_id: Optional[str] = None, detail: Optional[Dict[str, Any]] = None,
               note: Optional[str] = None) -> KnowledgeWorkspaceLog:
        log = KnowledgeWorkspaceLog(id=f"kw_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id,
                                    owner_id=owner_id, activity_type=activity_type, target_id=target_id,
                                    detail=detail, note=note)
        self.db.add(log)
        self.db.commit()
        return log

    def recent(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[KnowledgeWorkspaceLog]:
        return list(self.db.scalars(select(KnowledgeWorkspaceLog).where(
            KnowledgeWorkspaceLog.workspace_id == workspace_id, KnowledgeWorkspaceLog.owner_id == owner_id)
            .order_by(desc(KnowledgeWorkspaceLog.created_at)).limit(limit)))

    def activity_counts(self, workspace_id: str) -> Dict[str, int]:
        rows = self.db.execute(select(KnowledgeWorkspaceLog.activity_type, func.count()).where(
            KnowledgeWorkspaceLog.workspace_id == workspace_id)
            .group_by(KnowledgeWorkspaceLog.activity_type)).all()
        return {t: n for t, n in rows}
