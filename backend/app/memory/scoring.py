"""Memory Scoring Engine (Step 8) — explainable scores for graph hits.

A graph hit's relevance is a weighted blend of MEASURABLE graph signals (not model self-report):
- base_relevance    — the retriever's prior for its kind (entity > relationship > neighbor …).
- distance_decay    — closer to a seed = more relevant (1 / (1 + hop)).
- entity_confidence — the node's extraction confidence.
- relationship_wt   — the edge's weight (for relationship/evidence/backlink/reference hits).
- evidence_count    — how much provenance backs the hit.
- usage_frequency   — mention_count / degree (cumulative, persistent graph signal).
- graph_confidence  — the edge/node confidence.

Each signal ∈ [0,1] with a fixed weight; `score = Σ value·weight`, and the per-signal contributions are
stored on the hit for the retrieval-explanation UI (Step 12).
"""

from __future__ import annotations

from typing import Any, Dict

from app.memory.interfaces import GraphHit

WEIGHTS = {
    "base_relevance": 0.30,
    "distance_decay": 0.22,
    "entity_confidence": 0.14,
    "relationship_weight": 0.12,
    "evidence_count": 0.10,
    "usage_frequency": 0.07,
    "graph_confidence": 0.05,
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class MemoryScorer:
    name = "memory-scorer-v1"

    def score(self, hit: GraphHit, *, node_index: Dict[str, Any] = None) -> GraphHit:
        node_index = node_index or {}
        ent = node_index.get(hit.entity_id) if hit.entity_id else None

        distance_decay = 1.0 / (1.0 + max(0, hit.hop_distance))
        entity_confidence = float(getattr(ent, "confidence", 0.6)) if ent else hit.signals.get("rel_confidence", 0.6)
        relationship_weight = hit.signals.get("rel_weight", 0.0 if hit.kind in ("entity", "neighbor", "topic", "concept") else 0.6)
        evidence_count = _clamp(len(hit.provenance) / 3.0)
        mention = float(getattr(ent, "mention_count", 1)) if ent else 1.0
        degree = float(getattr(ent, "degree", hit.signals.get("degree", 0))) if ent else hit.signals.get("degree", 0.0)
        usage_frequency = _clamp((mention + degree) / 12.0)
        graph_confidence = hit.signals.get("rel_confidence", entity_confidence)

        vals = {
            "base_relevance": _clamp(hit.base_score),
            "distance_decay": _clamp(distance_decay),
            "entity_confidence": _clamp(entity_confidence),
            "relationship_weight": _clamp(relationship_weight),
            "evidence_count": evidence_count,
            "usage_frequency": usage_frequency,
            "graph_confidence": _clamp(graph_confidence),
        }
        hit.score = round(sum(vals[k] * WEIGHTS[k] for k in WEIGHTS), 6)
        hit.signals = {**hit.signals, **{f"sig_{k}": vals[k] for k in vals}}
        return hit
