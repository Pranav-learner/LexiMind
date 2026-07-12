"""Data access for the verification telemetry table (VerificationLog only)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.reasoning.models import VerificationLog


class VerificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, log: VerificationLog) -> VerificationLog:
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get(self, verification_id: str, owner_id: str) -> Optional[VerificationLog]:
        return self.db.scalar(select(VerificationLog).where(
            VerificationLog.id == verification_id, VerificationLog.owner_id == owner_id))

    def get_for_execution(self, execution_id: str, owner_id: str) -> Optional[VerificationLog]:
        return self.db.scalar(select(VerificationLog).where(
            VerificationLog.execution_id == execution_id, VerificationLog.owner_id == owner_id)
            .order_by(desc(VerificationLog.created_at)))

    def list(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[VerificationLog]:
        return list(self.db.scalars(
            select(VerificationLog).where(
                VerificationLog.workspace_id == workspace_id, VerificationLog.owner_id == owner_id)
            .order_by(desc(VerificationLog.created_at)).limit(limit)))

    def stats(self, workspace_id: str) -> dict:
        base = select(func.count()).select_from(VerificationLog).where(
            VerificationLog.workspace_id == workspace_id)
        total = int(self.db.scalar(base) or 0)
        verified = int(self.db.scalar(base.where(VerificationLog.status == "verified")) or 0)
        failed = int(self.db.scalar(base.where(VerificationLog.status == "failed")) or 0)
        avg_conf = float(self.db.scalar(
            select(func.coalesce(func.avg(VerificationLog.overall_confidence), 0.0))
            .where(VerificationLog.workspace_id == workspace_id)) or 0.0)
        return {"verifications": total, "verified": verified, "failed": failed,
                "avg_confidence": round(avg_conf, 4)}
