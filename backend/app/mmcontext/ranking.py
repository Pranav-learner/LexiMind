"""Cross-modal evidence ranking (Step 4) — score evidence of ANY modality on one comparable scale.

Phase-2 ranked text by an evidence score; this blends MANY signals so a diagram, a table, and a text
passage can be compared fairly. Each signal is weighted and its weighted contribution recorded on the
evidence (`ranking_contributions`) so the final ranking is fully explainable (Step 10).

Signals (weight):
- relevance        (0.35) — the fused/reranked retrieval confidence (semantic relevance to the query).
- retrieval_score  (0.10) — raw retrieval strength (before rerank).
- rerank_score     (0.10) — cross-modal reranker relevance.
- modality_importance (0.15) — the query-intent weight for this modality (a diagram question up-weights diagrams).
- confidence       (0.10) — vision/OCR extraction confidence (how much we trust the content).
- citation_quality (0.08) — a fully-traceable source is worth more.
- density          (0.07) — information density (unique-token ratio) — dense evidence over filler.
- multimodal_bonus (0.05) — evidence corroborated by multiple modalities (from dedup merges).

All signals are in [0,1]; the weighted sum is the evidence score (already in [0,1]). Pure + testable.
"""

from __future__ import annotations

import re
from typing import Dict, List

from app.mmcontext.schemas import MMEvidence

_WORD = re.compile(r"[a-z0-9]+")

WEIGHTS: Dict[str, float] = {
    "relevance": 0.35, "retrieval_score": 0.10, "rerank_score": 0.10, "modality_importance": 0.15,
    "confidence": 0.10, "citation_quality": 0.08, "density": 0.07, "multimodal_bonus": 0.05,
}


def _density(text: str) -> float:
    toks = _WORD.findall((text or "").lower())
    if not toks:
        return 0.0
    return min(1.0, len(set(toks)) / len(toks))


def rank(evidence: List[MMEvidence], modality_weights: Dict[str, float]) -> List[MMEvidence]:
    max_w = max(modality_weights.values()) if modality_weights else 1.0
    for ev in evidence:
        conf = ev.vision_confidence if ev.vision_confidence is not None else ev.ocr_confidence
        signals = {
            "relevance": _clamp(ev.base_score),
            "retrieval_score": _clamp(ev.retrieval_score),
            "rerank_score": _clamp(ev.rerank_score),
            "modality_importance": _clamp((modality_weights.get(ev.modality, 0.5) / max_w) if max_w else 0.5),
            "confidence": _clamp(conf if conf is not None else 0.6),
            "citation_quality": 1.0 if ev.citation().is_complete() else 0.5,
            "density": _density(ev.content),
            "multimodal_bonus": min(1.0, max(0, len(ev.contributing_modalities) - 1) * 0.5),
        }
        contributions = {k: round(WEIGHTS[k] * v, 5) for k, v in signals.items()}
        ev.ranking_contributions = contributions
        ev.evidence_score = round(sum(contributions.values()), 5)
    ranked = sorted(evidence, key=lambda e: e.evidence_score, reverse=True)
    for i, ev in enumerate(ranked, start=1):
        ev.rank = i
    return ranked


def _clamp(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0
