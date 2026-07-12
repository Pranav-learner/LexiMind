"""Confidence Propagation Engine (Step 6) — confidence flows evidence → edges → paths → conclusion.

Produces node / edge / path / overall confidence from MEASURABLE graph signals (not LLM self-report),
REUSING the Phase-6 `ConfidenceBreakdown`/`ConfidenceSignal` value objects (no duplication). Path
confidence is already multiplied along the path (with hop decay); this engine rolls those up into an
overall reasoning confidence and keeps the per-node/per-edge/per-path detail for the explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List

from app.reasoning.interfaces import ConfidenceBreakdown, ConfidenceSignal

WEIGHTS = {
    "path_confidence": 0.34,
    "graph_confidence": 0.22,
    "evidence_strength": 0.18,
    "verification": 0.14,
    "connectivity": 0.12,
}


def _band(x: float) -> str:
    return "high" if x >= 0.75 else "moderate" if x >= 0.5 else "low"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


@dataclass
class PropagatedConfidence:
    breakdown: ConfidenceBreakdown
    node_confidence: Dict[str, float] = field(default_factory=dict)
    edge_confidence: Dict[str, float] = field(default_factory=dict)
    path_confidence: List[float] = field(default_factory=list)

    @property
    def overall(self) -> float:
        return self.breakdown.overall

    def to_dict(self) -> Dict[str, Any]:
        return {"overall": self.breakdown.overall, "band": self.breakdown.band,
                "signals": [s.to_dict() for s in self.breakdown.signals],
                "explanation": self.breakdown.explanation,
                "node_confidence": {k: round(v, 4) for k, v in self.node_confidence.items()},
                "edge_confidence_avg": round(mean(self.edge_confidence.values()), 4) if self.edge_confidence else 0.0,
                "path_confidence": [round(x, 4) for x in self.path_confidence[:10]]}


class ConfidencePropagation:
    name = "propagation-v1"

    def propagate(self, paths, inferences, *, node_index: Dict[str, Any],
                  signals_in: Dict[str, Any]) -> PropagatedConfidence:
        node_conf = {nid: float(getattr(e, "confidence", 0.5)) for nid, e in node_index.items()}
        edge_conf: Dict[str, float] = {}
        for p in paths:
            for e in p.edges:
                edge_conf[e.rel_id] = e.confidence
        path_confs = [p.path_confidence for p in paths]

        path_confidence = mean(sorted(path_confs, reverse=True)[:5]) if path_confs else (0.4 if node_index else 0.0)
        graph_confidence = mean(edge_conf.values()) if edge_conf else mean(node_conf.values()) if node_conf else 0.0
        evidenced = sum(1 for p in paths for e in p.edges if e.evidence)
        total_edges = sum(p.length for p in paths) or 1
        evidence_strength = _clamp(evidenced / total_edges)
        verification = float(signals_in.get("verification", 0.6))
        seeds = max(1, signals_in.get("seed_count", 1))
        connectivity = _clamp(len(paths) / (seeds * 4))

        raw = {"path_confidence": path_confidence, "graph_confidence": graph_confidence,
               "evidence_strength": evidence_strength, "verification": verification,
               "connectivity": connectivity}
        details = {"path_confidence": f"mean of top paths over {len(paths)} path(s)",
                   "graph_confidence": f"mean edge confidence over {len(edge_conf)} edge(s)",
                   "evidence_strength": f"{evidenced}/{total_edges} edges carry evidence",
                   "verification": "graph-verification signal",
                   "connectivity": f"{len(paths)} path(s) from {seeds} seed(s)"}
        signals = [ConfidenceSignal(name=k, value=_clamp(raw[k]), weight=WEIGHTS[k], detail=details[k])
                   for k in WEIGHTS]
        overall = round(sum(s.contribution for s in signals), 4)
        band = _band(overall)
        explanation = (f"Reasoning confidence is {band} ({overall:.0%}); strongest signals: "
                       + ", ".join(f"{s.name} {s.value:.0%}" for s in sorted(signals, key=lambda s: s.contribution,
                                                                             reverse=True)[:2]) + ".")
        breakdown = ConfidenceBreakdown(overall=overall, band=band, signals=signals, explanation=explanation)
        return PropagatedConfidence(breakdown=breakdown, node_confidence=node_conf,
                                    edge_confidence=edge_conf, path_confidence=path_confs)
