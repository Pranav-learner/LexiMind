"""Continuous-learning service — feedback, learning cycles, review queue, datasets, metrics.

Composes the FeedbackManager, ErrorAnalyzer, LearningEngine, HumanReviewQueue, and DatasetBuilder into the
API surface. Everything is asynchronous-friendly (reads existing logs + this module's feedback; no user-request
coupling) and governed (recommendations enter as pending and require human approve/reject — never auto-applied).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.learning.analyzer import ErrorAnalyzer
from app.learning.dataset_builder import DatasetBuilder
from app.learning.engine import LearningEngine
from app.learning.feedback import FeedbackManager
from app.learning.repository import LearningRepository
from app.learning.review import HumanReviewQueue


class LearningService:
    def __init__(self, db: Session):
        self.db = db
        self.feedback = FeedbackManager(db)
        self.analyzer = ErrorAnalyzer(db)
        self.engine = LearningEngine(db)
        self.queue = HumanReviewQueue(db)
        self.builder = DatasetBuilder(db)
        self.repo = LearningRepository(db)

    # ------------------------------------------------------------------ feedback (Step 3)
    def submit_feedback(self, workspace_id, owner_id, **kw) -> Dict[str, Any]:
        fb = self.feedback.submit(workspace_id, owner_id, **kw)
        return FeedbackManager.to_dict(fb)

    def feedback_history(self, workspace_id, owner_id, *, limit=100, sentiment=None) -> List[Dict[str, Any]]:
        return [FeedbackManager.to_dict(f) for f in
                self.feedback.list(workspace_id, owner_id, limit=limit, sentiment=sentiment)]

    def feedback_summary(self, workspace_id, owner_id) -> Dict[str, Any]:
        return self.feedback.summary(workspace_id, owner_id)

    # ------------------------------------------------------------------ insights (Step 4/10)
    def insights(self, workspace_id, owner_id) -> Dict[str, Any]:
        analysis = self.analyzer.analyze(workspace_id, owner_id)
        return {"total_failures": analysis["total"], "by_category": analysis["by_category"],
                "clusters": [c.to_dict() for c in analysis["clusters"]],
                "feedback": self.feedback.summary(workspace_id, owner_id)}

    def generate(self, workspace_id, owner_id) -> Dict[str, Any]:
        """Preview recommendations without persisting."""
        result = self.engine.generate(workspace_id, owner_id)
        return {"analysis": result["analysis"],
                "recommendations": [r.to_dict() for r in result["recommendations"]]}

    def run_cycle(self, workspace_id, owner_id) -> Dict[str, Any]:
        return self.engine.run_cycle(workspace_id, owner_id)

    # ------------------------------------------------------------------ review queue (Step 9/16)
    def recommendations(self, workspace_id, owner_id, *, status="pending", category=None, limit=100) -> List[Dict[str, Any]]:
        return [HumanReviewQueue.to_dict(r) for r in
                self.queue.queue(workspace_id, owner_id, status=status, category=category, limit=limit)]

    def recommendation(self, rec_id, owner_id) -> Dict[str, Any]:
        return HumanReviewQueue.to_dict(self.queue.get(rec_id, owner_id))

    def approve(self, rec_id, owner_id, *, note="") -> Dict[str, Any]:
        return HumanReviewQueue.to_dict(self.queue.approve(rec_id, owner_id, note=note))

    def reject(self, rec_id, owner_id, *, note="") -> Dict[str, Any]:
        return HumanReviewQueue.to_dict(self.queue.reject(rec_id, owner_id, note=note))

    # ------------------------------------------------------------------ dataset builder (Step 5)
    def build_dataset(self, workspace_id, owner_id, *, name=None) -> Dict[str, Any]:
        signals = self.analyzer.collect(workspace_id, owner_id)
        return self.builder.build_from_failures(workspace_id, owner_id, signals=signals, name=name)

    # ------------------------------------------------------------------ improvement report / dashboard (Step 12)
    def improvement_report(self, workspace_id, owner_id) -> Dict[str, Any]:
        counts = self.repo.recommendation_counts(workspace_id, owner_id)
        cycles = self.repo.cycles(workspace_id, owner_id, limit=20)
        return {"recommendation_status": counts,
                "by_category": self.repo.category_counts(workspace_id, owner_id),
                "cycles": [{"id": c.id, "failures_analyzed": c.failures_analyzed, "clusters": c.clusters,
                            "recommendations_generated": c.recommendations_generated,
                            "avg_confidence": c.avg_confidence, "affected_components": c.affected_components,
                            "created_at": c.created_at.isoformat() if c.created_at else None} for c in cycles],
                "approved": counts.get("approved", 0), "rejected": counts.get("rejected", 0),
                "pending": counts.get("pending", 0)}

    def dashboard(self, workspace_id, owner_id) -> Dict[str, Any]:
        return {"feedback": self.feedback.summary(workspace_id, owner_id),
                "insights": self.insights(workspace_id, owner_id),
                "review": self.improvement_report(workspace_id, owner_id),
                "pending_recommendations": self.recommendations(workspace_id, owner_id, status="pending", limit=10)}
