"""Human Review Queue (Step 9) + governance (Step 16).

Recommendations are governed proposals — they enter as `status="pending"` and a developer must approve or
reject before anything is ever acted on (this module NEVER auto-applies). Approve/reject is an auditable
state transition (reviewer + timestamp + note). Future enterprise approval workflows plug in here; the
recommendation record is the version-history/audit surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.learning.errors import RecommendationNotFound
from app.learning.models import LearningRecommendation


class HumanReviewQueue:
    def __init__(self, db: Session):
        self.db = db

    def queue(self, workspace_id: str, owner_id: str, *, status: str = "pending",
              category: Optional[str] = None, limit: int = 100) -> List[LearningRecommendation]:
        stmt = select(LearningRecommendation).where(
            LearningRecommendation.workspace_id == workspace_id,
            LearningRecommendation.owner_id == owner_id)
        if status:
            stmt = stmt.where(LearningRecommendation.status == status)
        if category:
            stmt = stmt.where(LearningRecommendation.category == category)
        return list(self.db.scalars(stmt.order_by(desc(LearningRecommendation.created_at)).limit(limit)))

    def get(self, rec_id: str, owner_id: str) -> LearningRecommendation:
        rec = self.db.scalar(select(LearningRecommendation).where(
            LearningRecommendation.id == rec_id, LearningRecommendation.owner_id == owner_id))
        if rec is None:
            raise RecommendationNotFound(rec_id)
        return rec

    def _decide(self, rec_id: str, owner_id: str, *, status: str, note: str) -> LearningRecommendation:
        rec = self.get(rec_id, owner_id)
        rec.status = status
        rec.reviewer = owner_id
        rec.review_note = note or ""
        rec.reviewed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def approve(self, rec_id: str, owner_id: str, *, note: str = "") -> LearningRecommendation:
        # NOTE: approval records intent only — it does NOT mutate production behavior (Step 16 governance).
        return self._decide(rec_id, owner_id, status="approved", note=note)

    def reject(self, rec_id: str, owner_id: str, *, note: str = "") -> LearningRecommendation:
        return self._decide(rec_id, owner_id, status="rejected", note=note)

    @staticmethod
    def to_dict(rec: LearningRecommendation) -> Dict[str, Any]:
        return {"id": rec.id, "category": rec.category, "title": rec.title, "reason": rec.reason,
                "evidence": rec.evidence or {}, "expected_impact": rec.expected_impact,
                "confidence": rec.confidence, "severity": rec.severity,
                "affected_components": rec.affected_components or [], "cluster_id": rec.cluster_id,
                "status": rec.status, "reviewer": rec.reviewer, "review_note": rec.review_note,
                "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
                "created_at": rec.created_at.isoformat() if rec.created_at else None}
