"""Reciprocal Rank Fusion (RRF).

Combines several ranked candidate lists (e.g. dense + sparse) into one ranking using
only ordinal rank, not raw scores. This is the right tool for hybrid search because
dense similarity (cosine/L2-derived) and BM25 scores live on incomparable scales —
normalizing them is brittle, whereas ranks are always comparable.

    RRF(d) = Σ_r  1 / (k + rank_r(d))

where the sum is over every ranked list r in which document d appears, rank_r(d) is
d's 1-based position in list r, and k is a smoothing constant (Cormack et al. 2009
use k=60) that damps the influence of very-high-rank items.

Pure functions only — no I/O, no model loading — so this is cheap to unit test.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from app.retrieval.schemas import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[RetrievedChunk]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
    top_k: int | None = None,
) -> List[RetrievedChunk]:
    """Fuse multiple ranked lists of RetrievedChunk into one.

    Args:
        ranked_lists: each inner sequence is one retriever's results, ordered best-first.
        k: RRF smoothing constant. Larger k flattens the contribution of top ranks.
        weights: optional per-list weights (e.g. trust dense more than sparse). Defaults
            to 1.0 for every list. Must match len(ranked_lists) when provided.
        top_k: if set, truncate the fused result to this many chunks.

    Returns:
        A new list of RetrievedChunk ordered by descending fused score. Duplicates
        (same chunk_id across lists) are merged; their fused score is the weighted sum
        of reciprocal ranks. `retriever` is set to "rrf" and `rank` is the 1-based
        fused position. Metadata/text are taken from the first occurrence seen.
    """
    if k <= 0:
        raise ValueError("RRF k must be a positive integer")
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights must have the same length as ranked_lists")

    fused_score: Dict[str, float] = {}
    representative: Dict[str, RetrievedChunk] = {}
    contributors: Dict[str, set] = {}

    for list_idx, ranked in enumerate(ranked_lists):
        weight = weights[list_idx]
        for position, chunk in enumerate(ranked, start=1):  # 1-based rank
            cid = chunk.chunk_id
            fused_score[cid] = fused_score.get(cid, 0.0) + weight * (1.0 / (k + position))
            contributors.setdefault(cid, set())
            if chunk.retriever:
                contributors[cid].add(chunk.retriever)
            if cid not in representative:
                representative[cid] = chunk

    ordered = sorted(fused_score.items(), key=lambda kv: kv[1], reverse=True)

    results: List[RetrievedChunk] = []
    for rank, (cid, score) in enumerate(ordered, start=1):
        base = representative[cid]
        src = "+".join(sorted(contributors[cid])) or "rrf"
        results.append(
            RetrievedChunk(
                chunk_id=base.chunk_id,
                text=base.text,
                metadata=base.metadata,
                score=score,
                rank=rank,
                retriever=f"rrf({src})",
            )
        )
        if top_k is not None and len(results) >= top_k:
            break

    return results
