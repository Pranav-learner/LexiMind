"""Data access for continuous learning — cycle logs + recommendation aggregates."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.learning.models import LearningCycleLog, LearningRecommendation


class LearningRepository:
    def __init__(self, db: Session):
        self.db = db

    def cycles(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[LearningCycleLog]:
        return list(self.db.scalars(select(LearningCycleLog).where(
            LearningCycleLog.workspace_id == workspace_id, LearningCycleLog.owner_id == owner_id)
            .order_by(desc(LearningCycleLog.created_at)).limit(limit)))

    def recommendation_counts(self, workspace_id: str, owner_id: str) -> Dict[str, int]:
        rows = self.db.execute(select(LearningRecommendation.status, func.count()).where(
            LearningRecommendation.workspace_id == workspace_id,
            LearningRecommendation.owner_id == owner_id).group_by(LearningRecommendation.status)).all()
        return {status: count for status, count in rows}

    def category_counts(self, workspace_id: str, owner_id: str) -> Dict[str, int]:
        rows = self.db.execute(select(LearningRecommendation.category, func.count()).where(
            LearningRecommendation.workspace_id == workspace_id,
            LearningRecommendation.owner_id == owner_id).group_by(LearningRecommendation.category)).all()
        return {cat: count for cat, count in rows}
