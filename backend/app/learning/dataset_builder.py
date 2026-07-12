"""Dataset Builder (Step 5) — turn failures into future benchmarks.

Reuses the Evaluation Framework (M1) models directly: it materializes failure signals + correction feedback
into an `EvalDataset` + `EvalItem` rows so "every important failure becomes a regression test". It does NOT
re-implement datasets/metrics — it writes into the existing eval tables that the Evaluation runner already
consumes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.learning.interfaces import FailureSignal
from app.learning.models import Feedback


class DatasetBuilder:
    def __init__(self, db: Session):
        self.db = db

    def build_from_failures(self, workspace_id: str, owner_id: str, *, signals: List[FailureSignal],
                            name: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        from app.evaluation.models import EvalDataset, EvalItem

        # prefer signals that carry a usable question/correction (feedback corrections + verification cases)
        items_src: List[Dict[str, Any]] = []
        # corrections from feedback = golden expected answers
        corrections = list(self.db.query(Feedback).filter(
            Feedback.workspace_id == workspace_id, Feedback.kind == "correction").limit(limit))
        for c in corrections:
            q = (c.comment or c.signals.get("question") if isinstance(c.signals, dict) else "") or c.comment
            if c.correction:
                items_src.append({"question": (q or c.comment or "corrected item")[:500],
                                  "expected_answer": c.correction[:2000], "difficulty": "hard",
                                  "tags": ["failure", "correction"]})
        # remaining failure signals become hard examples (no golden answer yet — flagged for review)
        for s in signals[: max(0, limit - len(items_src))]:
            if s.category in ("hallucination", "missing_retrieval", "bad_citation", "low_confidence"):
                items_src.append({"question": (s.detail or s.category)[:500], "expected_answer": "",
                                  "difficulty": "hard", "tags": ["failure", s.category]})

        if not items_src:
            return {"created": False, "reason": "no failure items available to build a dataset"}

        ds = EvalDataset(id=f"ds_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                         name=name or f"Failure regression set {datetime.utcnow().strftime('%Y%m%d')}",
                         version="1", description="Auto-generated from continuous-learning failure analysis.",
                         tags=["auto", "failure"], item_count=len(items_src),
                         difficulty_distribution={"hard": len(items_src)})
        self.db.add(ds)
        for it in items_src:
            self.db.add(EvalItem(id=f"ei_{uuid.uuid4().hex[:16]}", dataset_id=ds.id, workspace_id=workspace_id,
                                 owner_id=owner_id, question=it["question"], expected_answer=it["expected_answer"],
                                 difficulty=it["difficulty"], tags=it["tags"], meta={"source": "continuous_learning"}))
        self.db.commit()
        return {"created": True, "dataset_id": ds.id, "name": ds.name, "item_count": len(items_src),
                "tags": ds.tags}
