"""Error Analysis Engine (Step 4).

Reads failure evidence from feedback + the existing logs (VerificationLog / AgentTaskLog / OptimizationRunLog
— CONSUMED, never re-logged), normalizes each into a `FailureSignal` with a category, then clusters similar
failures by (category + keyword signature). Clusters are what the learning engines and dataset builder act on
— "every important failure becomes a future benchmark" starts here.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.learning.interfaces import FailureCluster, FailureSignal
from app.learning.models import Feedback

_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or", "in", "on", "for",
         "with", "what", "how", "why", "does", "did", "this", "that", "it", "be"}
_FAILED_STATUSES = {"failed", "error", "cancelled", "unsupported"}


def _keywords(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9']+", (text or "").lower())
            if len(w) > 2 and w not in _STOP][:8]


class ErrorAnalyzer:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ collect signals
    def collect(self, workspace_id: str, owner_id: str, *, limit: int = 500) -> List[FailureSignal]:
        signals: List[FailureSignal] = []
        signals += self._from_feedback(workspace_id, limit)
        signals += self._from_verification(workspace_id, owner_id, limit)
        signals += self._from_agents(workspace_id, owner_id, limit)
        signals += self._from_optimization(workspace_id, owner_id, limit)
        return signals

    def _from_feedback(self, workspace_id: str, limit: int) -> List[FailureSignal]:
        rows = list(self.db.scalars(select(Feedback).where(
            Feedback.workspace_id == workspace_id, Feedback.sentiment == "negative")
            .order_by(desc(Feedback.created_at)).limit(limit)))
        out = []
        for r in rows:
            cat = "bad_citation" if r.target_type == "citation" else (
                  "missing_retrieval" if r.target_type == "retrieval" else (
                  "agent_failure" if r.target_type == "agent" else "negative_feedback"))
            text = r.correction or r.comment or r.target_type
            out.append(FailureSignal(source="feedback", category=cat, target_id=r.target_id,
                                     detail=text, severity="warning", keywords=_keywords(text),
                                     signals={"kind": r.kind, "rating": r.rating}))
        return out

    def _from_verification(self, workspace_id, owner_id, limit) -> List[FailureSignal]:
        try:
            from app.reasoning.models import VerificationLog
        except Exception:
            return []
        rows = list(self.db.scalars(select(VerificationLog).where(
            VerificationLog.workspace_id == workspace_id, VerificationLog.owner_id == owner_id)
            .order_by(desc(VerificationLog.created_at)).limit(limit)))
        out = []
        for r in rows:
            unsupported = getattr(r, "unsupported", 0) or 0
            contradictions = getattr(r, "contradictions_found", 0) or 0
            citation_failures = getattr(r, "citation_failures", 0) or 0
            conf = getattr(r, "overall_confidence", 1.0) or 1.0
            if contradictions or unsupported:
                cat, sev = "hallucination", ("critical" if contradictions else "warning")
            elif citation_failures:
                cat, sev = "bad_citation", "warning"
            elif conf < 0.4:
                cat, sev = "low_confidence", "warning"
            else:
                continue
            out.append(FailureSignal(source="verification", category=cat, target_id=str(r.id),
                                     detail=f"{getattr(r,'task_type','')} conf={conf:.2f} "
                                            f"unsupported={unsupported} contradictions={contradictions}",
                                     severity=sev, keywords=_keywords(getattr(r, "task_type", "")),
                                     signals={"confidence": conf, "unsupported": unsupported,
                                              "contradictions": contradictions, "citation_failures": citation_failures}))
        return out

    def _from_agents(self, workspace_id, owner_id, limit) -> List[FailureSignal]:
        try:
            from app.agents.task_service import AgentTaskLog
        except Exception:
            try:
                from app.agents.models import AgentTaskLog  # type: ignore
            except Exception:
                return []
        rows = list(self.db.scalars(select(AgentTaskLog).where(
            AgentTaskLog.workspace_id == workspace_id, AgentTaskLog.owner_id == owner_id)
            .order_by(desc(AgentTaskLog.created_at)).limit(limit)))
        out = []
        for r in rows:
            status = getattr(r, "status", "") or ""
            success = getattr(r, "success", True)
            retries = getattr(r, "retries", 0) or 0
            if status in _FAILED_STATUSES or success is False or retries >= 2:
                detail = getattr(r, "error", "") or f"{getattr(r,'agent','')}/{getattr(r,'task_type','')}"
                out.append(FailureSignal(source="agent", category="agent_failure",
                                         target_id=str(r.id), detail=str(detail),
                                         severity="critical" if status in _FAILED_STATUSES else "warning",
                                         keywords=_keywords(f"{getattr(r,'agent','')} {getattr(r,'task_type','')}"),
                                         signals={"status": status, "retries": retries,
                                                  "evidence_count": getattr(r, "evidence_count", 0)}))
        return out

    def _from_optimization(self, workspace_id, owner_id, limit) -> List[FailureSignal]:
        try:
            from app.optimization.models import OptimizationRunLog
        except Exception:
            return []
        rows = list(self.db.scalars(select(OptimizationRunLog).where(
            OptimizationRunLog.workspace_id == workspace_id, OptimizationRunLog.owner_id == owner_id)
            .order_by(desc(OptimizationRunLog.created_at)).limit(limit)))
        out = []
        for r in rows:
            latency = getattr(r, "latency_ms", 0) or 0
            quality = getattr(r, "quality_impact", 1.0) or 0.0
            if latency > 3000:
                out.append(FailureSignal(source="optimization", category="slow_response",
                                         target_id=str(r.id), detail=f"latency {latency:.0f}ms",
                                         severity="warning", keywords=_keywords(getattr(r, "query", "")),
                                         signals={"latency_ms": latency, "model": getattr(r, "model_selected", "")}))
        return out

    # ------------------------------------------------------------------ cluster
    def cluster(self, signals: List[FailureSignal]) -> List[FailureCluster]:
        buckets: Dict[str, List[FailureSignal]] = defaultdict(list)
        for s in signals:
            sig = s.category + "|" + (s.keywords[0] if s.keywords else "")
            cid = hashlib.sha1(sig.encode()).hexdigest()[:10]
            buckets[cid].append(s)
        clusters = []
        for cid, members in buckets.items():
            cat = members[0].category
            sev = "critical" if any(m.severity == "critical" for m in members) else members[0].severity
            kws: List[str] = []
            for m in members:
                for k in m.keywords:
                    if k not in kws:
                        kws.append(k)
            clusters.append(FailureCluster(cluster_id=cid, category=cat, count=len(members), severity=sev,
                                           sample_details=[m.detail[:120] for m in members[:3]], keywords=kws[:8]))
        clusters.sort(key=lambda c: (c.severity == "critical", c.count), reverse=True)
        return clusters

    def analyze(self, workspace_id: str, owner_id: str, *, limit: int = 500) -> Dict[str, Any]:
        signals = self.collect(workspace_id, owner_id, limit=limit)
        clusters = self.cluster(signals)
        by_category: Dict[str, int] = {}
        for s in signals:
            by_category[s.category] = by_category.get(s.category, 0) + 1
        return {"signals": signals, "clusters": clusters, "total": len(signals), "by_category": by_category}
