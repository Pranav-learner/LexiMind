"""Multimodal fusion (Step 5) — a generalized, configurable, modality-agnostic fusion framework.

Generalizes Phase-1 RRF (dense ⊕ sparse) to N modalities. Each retriever's results are already
normalized (see normalize.py) and rank-ordered; fusion combines them with per-modality WEIGHTS
(from intent analysis) and deduplicates the SAME underlying knowledge cited by multiple modalities
(e.g. a page found by both text and OCR) by a stable `key`, summing their contributions.

Two strategies:
- `rrf` (default): weighted Reciprocal Rank Fusion — robust to score scale, uses rank not magnitude.
- `weighted_sum`: weight × normalized_score — respects score magnitude when calibrated.

Adding a new modality is just adding it to the input dict + a weight — no code change (plug-and-play).
"""

from __future__ import annotations

from typing import Dict, List

from app.mmretrieval.schemas import RetrievalHit

RRF_K = 60


def fuse(by_modality: Dict[str, List[RetrievalHit]], weights: Dict[str, float],
         *, strategy: str = "rrf") -> List[RetrievalHit]:
    """Fuse per-modality result lists into one ranked list with full contribution accounting."""
    merged: Dict[str, RetrievalHit] = {}

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
                # Keep the richest content/title across the merged sources.
                if hit.normalized_score > existing.normalized_score:
                    existing.normalized_score = hit.normalized_score
                if len(hit.content) > len(existing.content):
                    existing.content = hit.content
                existing.metadata.setdefault("also_found_by", []).append(modality)

    ranked = sorted(merged.values(), key=lambda h: h.fusion_score, reverse=True)
    for i, h in enumerate(ranked, start=1):
        h.final_rank = i
    return ranked
