"""Value objects + Protocols for Continuous Learning (Phase 8, Module 4).

Interface-driven: every learning engine (prompt/retrieval/agent) implements the `LearningSource` protocol —
it consumes failure signals and emits `LearningRecommendation` value objects. A future RL/active-learning
engine plugs in by implementing the same protocol; the orchestrator never changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class FailureSignal:
    """A normalized failure observation drawn from feedback OR an existing log."""
    source: str                          # feedback|verification|agent|optimization
    category: str                        # missing_retrieval|hallucination|bad_citation|slow_response|agent_failure|low_confidence|negative_feedback
    target_id: str = ""
    detail: str = ""
    severity: str = "warning"            # info|warning|critical
    keywords: List[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "category": self.category, "target_id": self.target_id,
                "detail": self.detail[:280], "severity": self.severity, "keywords": self.keywords[:8],
                "signals": self.signals}


@dataclass
class FailureCluster:
    cluster_id: str
    category: str
    count: int
    severity: str
    sample_details: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"cluster_id": self.cluster_id, "category": self.category, "count": self.count,
                "severity": self.severity, "sample_details": self.sample_details[:3],
                "keywords": self.keywords[:8]}


@dataclass
class LearningRec:
    """An explainable, governed recommendation (never auto-applied)."""
    category: str                        # prompt|retrieval|agent|dataset|routing|graph|context
    title: str
    reason: str
    expected_impact: str
    confidence: float = 0.5
    severity: str = "info"
    evidence: Dict[str, Any] = field(default_factory=dict)
    affected_components: List[str] = field(default_factory=list)
    cluster_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"category": self.category, "title": self.title, "reason": self.reason,
                "expected_impact": self.expected_impact, "confidence": round(self.confidence, 3),
                "severity": self.severity, "evidence": self.evidence,
                "affected_components": self.affected_components, "cluster_id": self.cluster_id}


@runtime_checkable
class LearningSource(Protocol):
    """A pluggable learning engine: failure signals + clusters → recommendations."""
    def analyze(self, signals: List[FailureSignal], clusters: List[FailureCluster]) -> List[LearningRec]: ...
