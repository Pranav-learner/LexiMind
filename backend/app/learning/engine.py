"""Learning Engine (Steps 2 & 10) — orchestrates one continuous-learning cycle.

Composes: ErrorAnalyzer (collect + cluster failure signals) → the pluggable learning engines
(prompt/retrieval/agent) → an aggregated, de-duplicated set of explainable `LearningRec`s → persisted as
`pending` recommendations in the human review queue → a `LearningCycleLog` summary. It CONSUMES signals from
every subsystem and PRODUCES governed proposals; it never mutates production. Designed to run asynchronously
(off the user-request path).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.learning.analyzer import ErrorAnalyzer
from app.learning.interfaces import LearningRec
from app.learning.learners import AgentLearningEngine, PromptLearningEngine, RetrievalLearningEngine
from app.learning.models import LearningCycleLog, LearningRecommendation


class LearningEngine:
    def __init__(self, db: Session):
        self.db = db
        self.analyzer = ErrorAnalyzer(db)
        self.sources = [PromptLearningEngine(), RetrievalLearningEngine(), AgentLearningEngine()]

    def generate(self, workspace_id: str, owner_id: str, *, limit: int = 500) -> Dict[str, Any]:
        """Analyze → recommend (pure; no persistence). The preview of a cycle."""
        analysis = self.analyzer.analyze(workspace_id, owner_id, limit=limit)
        signals, clusters = analysis["signals"], analysis["clusters"]
        recs: List[LearningRec] = []
        for src in self.sources:
            recs.extend(src.analyze(signals, clusters))
        # de-dup by (category, title)
        seen = set()
        unique: List[LearningRec] = []
        for r in recs:
            key = (r.category, r.title)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return {"analysis": {"total": analysis["total"], "by_category": analysis["by_category"],
                             "clusters": [c.to_dict() for c in clusters]},
                "recommendations": unique}

    def run_cycle(self, workspace_id: str, owner_id: str, *, limit: int = 500) -> Dict[str, Any]:
        """Full cycle: generate + PERSIST pending recommendations + log the cycle."""
        result = self.generate(workspace_id, owner_id, limit=limit)
        recs: List[LearningRec] = result["recommendations"]
        persisted: List[LearningRecommendation] = []
        for r in recs:
            row = LearningRecommendation(
                id=f"rec_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                category=r.category, title=r.title, reason=r.reason, evidence=r.evidence,
                expected_impact=r.expected_impact, confidence=r.confidence, severity=r.severity,
                affected_components=r.affected_components, cluster_id=r.cluster_id, status="pending")
            self.db.add(row)
            persisted.append(row)

        components = sorted({c for r in recs for c in r.affected_components})
        avg_conf = round(sum(r.confidence for r in recs) / len(recs), 3) if recs else 0.0
        cycle = LearningCycleLog(
            id=f"cyc_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            feedback_count=sum(1 for s in self.analyzer.collect(workspace_id, owner_id, limit=limit)
                               if s.source == "feedback"),
            failures_analyzed=result["analysis"]["total"], clusters=len(result["analysis"]["clusters"]),
            recommendations_generated=len(recs), affected_components=components, avg_confidence=avg_conf)
        self.db.add(cycle)
        self.db.commit()
        return {"cycle_id": cycle.id, "recommendations_generated": len(recs),
                "recommendation_ids": [r.id for r in persisted],
                "analysis": result["analysis"], "avg_confidence": avg_conf,
                "affected_components": components}
