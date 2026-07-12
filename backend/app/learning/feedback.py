"""Feedback Manager (Step 3) — the unified real-world feedback surface.

One structured store for every feedback kind (thumbs / star / text / correction / citation / retrieval /
agent / graph / media / workspace), from authenticated OR anonymous users. Derives a sentiment so the error
analyzer can treat negative feedback as a failure signal without re-parsing.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.learning.models import Feedback

_NEGATIVE_KINDS = {"thumbs_down"}
_POSITIVE_KINDS = {"thumbs_up"}


def _derive_sentiment(kind: str, rating: Optional[int], comment: str) -> str:
    if kind in _NEGATIVE_KINDS:
        return "negative"
    if kind in _POSITIVE_KINDS:
        return "positive"
    if kind == "star" and rating is not None:
        return "negative" if rating <= 2 else ("positive" if rating >= 4 else "neutral")
    if kind == "correction":
        return "negative"                       # a correction implies the answer was wrong
    return "neutral"


class FeedbackManager:
    def __init__(self, db: Session):
        self.db = db

    def submit(self, workspace_id: str, owner_id: Optional[str], *, target_type: str, target_id: str,
               kind: str, rating: Optional[int] = None, comment: str = "", correction: str = "",
               signals: Optional[Dict[str, Any]] = None) -> Feedback:
        fb = Feedback(id=f"fb_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                      target_type=target_type, target_id=target_id or "", kind=kind, rating=rating,
                      sentiment=_derive_sentiment(kind, rating, comment), comment=comment or "",
                      correction=correction or "", signals=signals or {})
        self.db.add(fb)
        self.db.commit()
        self.db.refresh(fb)
        return fb

    def list(self, workspace_id: str, owner_id: str, *, limit: int = 100,
             sentiment: Optional[str] = None) -> List[Feedback]:
        stmt = select(Feedback).where(Feedback.workspace_id == workspace_id)
        if sentiment:
            stmt = stmt.where(Feedback.sentiment == sentiment)
        return list(self.db.scalars(stmt.order_by(desc(Feedback.created_at)).limit(limit)))

    def summary(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        rows = self.list(workspace_id, owner_id, limit=1000)
        by_sentiment: Dict[str, int] = {}
        by_kind: Dict[str, int] = {}
        by_target: Dict[str, int] = {}
        ratings: List[int] = []
        for r in rows:
            by_sentiment[r.sentiment] = by_sentiment.get(r.sentiment, 0) + 1
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
            by_target[r.target_type] = by_target.get(r.target_type, 0) + 1
            if r.rating is not None:
                ratings.append(r.rating)
        total = len(rows)
        neg = by_sentiment.get("negative", 0)
        return {"total": total, "by_sentiment": by_sentiment, "by_kind": by_kind, "by_target": by_target,
                "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "negative_rate": round(neg / total, 3) if total else 0.0,
                "corrections": by_kind.get("correction", 0)}

    @staticmethod
    def to_dict(fb: Feedback) -> Dict[str, Any]:
        return {"id": fb.id, "target_type": fb.target_type, "target_id": fb.target_id, "kind": fb.kind,
                "rating": fb.rating, "sentiment": fb.sentiment, "comment": fb.comment,
                "correction": fb.correction, "anonymous": fb.owner_id is None,
                "created_at": fb.created_at.isoformat() if fb.created_at else None}
