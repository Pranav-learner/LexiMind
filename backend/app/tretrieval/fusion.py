"""Temporal fusion (Step 5) — generalized weighted fusion + a temporal-proximity signal.

Extends the mmretrieval fusion idea (weighted RRF / weighted-sum, dedup by stable `key`, contribution
accounting) with TIME: hits that cluster around the highest-scoring moment get a small adjacency
bonus, because in temporal media the answer is usually a *neighbourhood* on the timeline, not one
isolated segment. Configurable weights; adding a modality is just adding it to the input dict.
"""

from __future__ import annotations

from typing import Dict, List

from app.tretrieval.schemas import TemporalHit

RRF_K = 60
_ADJACENCY_WINDOW_MS = 30_000   # hits within 30s of the top moment get an adjacency nudge
_ADJACENCY_BONUS = 0.15


def fuse(by_modality: Dict[str, List[TemporalHit]], weights: Dict[str, float],
         *, strategy: str = "rrf") -> List[TemporalHit]:
    """Fuse per-modality temporal hits into one ranked list with full contribution accounting."""
    merged: Dict[str, TemporalHit] = {}

    for modality, hits in by_modality.items():
        w = weights.get(modality, 0.5)
        for hit in hits:
            if strategy == "weighted_sum":
                contribution = w * hit.normalized_score
            else:  # weighted RRF
                contribution = w / (RRF_K + max(0, hit.rank_in_modality))

            existing = merged.get(hit.key)
            if existing is None:
                hit.fusion_score = contribution
                hit.fusion_contributions = {modality: round(contribution, 6)}
                hit.contributing_modalities = [modality]
                merged[hit.key] = hit
            else:
                existing.fusion_score += contribution
                existing.fusion_contributions[modality] = round(
                    existing.fusion_contributions.get(modality, 0.0) + contribution, 6)
                if modality not in existing.contributing_modalities:
                    existing.contributing_modalities.append(modality)
                if hit.normalized_score > existing.normalized_score:
                    existing.normalized_score = hit.normalized_score
                if len(hit.content) > len(existing.content):
                    existing.content = hit.content
                existing.metadata.setdefault("also_found_by", []).append(modality)

    ranked = sorted(merged.values(), key=lambda h: h.fusion_score, reverse=True)

    # Temporal adjacency: nudge hits near the top moment (same document) up a touch.
    if ranked:
        anchor = ranked[0]
        for h in ranked[1:]:
            if h.document_id == anchor.document_id and h.key != anchor.key:
                mid_h = (h.start_ms + h.end_ms) / 2
                mid_a = (anchor.start_ms + anchor.end_ms) / 2
                if abs(mid_h - mid_a) <= _ADJACENCY_WINDOW_MS:
                    h.fusion_score += _ADJACENCY_BONUS * anchor.fusion_score
                    h.metadata["temporal_adjacent"] = True
        ranked = sorted(merged.values(), key=lambda h: h.fusion_score, reverse=True)

    for i, h in enumerate(ranked, start=1):
        h.final_rank = i
    return ranked
