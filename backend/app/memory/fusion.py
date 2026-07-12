"""Hybrid Graph + Vector Fusion (Step 7) — REUSES the Phase-4 fusion, adding `graph` as a modality.

`app.mmretrieval.fusion.fuse` is modality-agnostic ("adding a new modality is just adding it to the input
dict + a weight"). So graph retrieval becomes a first-class provider: graph hits are adapted to
`RetrievalHit`s (modality="graph") and fused with the vector/multimodal hits through the SAME weighted
RRF — no fusion logic is duplicated or replaced.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.memory.interfaces import GraphHit

DEFAULT_WEIGHTS = {"graph": 0.6, "text": 0.5, "ocr": 0.4, "image": 0.35, "table": 0.4, "temporal": 0.45}


def hybrid_fuse(graph_hits: List[GraphHit], vector_hits: Optional[List] = None,
                weights: Optional[Dict[str, float]] = None):
    from app.mmretrieval.fusion import fuse

    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    ranked = sorted(graph_hits, key=lambda h: h.score, reverse=True)
    for i, h in enumerate(ranked, start=1):
        h.rank_in_modality = i
    by_modality: Dict[str, List] = {"graph": [h.to_retrieval_hit() for h in ranked]}

    if vector_hits:
        # group the vector RetrievalHits by their own modality so weights apply correctly
        for vh in vector_hits:
            by_modality.setdefault(vh.modality, []).append(vh)

    fused = fuse(by_modality, weights, strategy="rrf")
    return fused
