"""Score normalization (Step 7) — make heterogeneous retriever scores comparable before fusion.

Every retriever produces its own score distribution (BM25 magnitudes, cosine ∈ [-1,1], lexical
overlap counts). Fusing them directly would let whichever retriever happens to have the largest raw
range dominate. We normalize EACH retriever's result set independently to [0,1] so fusion compares
like with like.

Default strategy: min-max within the retriever's own results (rank-preserving, bounded, robust to a
retriever's absolute scale). A z-score→sigmoid variant is provided for score sets with outliers.
Pure functions → unit-testable.
"""

from __future__ import annotations

from math import exp
from typing import List


def minmax(scores: List[float]) -> List[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        # All equal → give a uniform mid score (they're equally good within this retriever).
        return [1.0 if hi > 0 else 0.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def zscore_sigmoid(scores: List[float]) -> List[float]:
    if not scores:
        return []
    n = len(scores)
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / n
    std = var ** 0.5
    if std < 1e-9:
        return [0.5 for _ in scores]
    return [1.0 / (1.0 + exp(-((s - mean) / std))) for s in scores]


def normalize(scores: List[float], strategy: str = "minmax") -> List[float]:
    if strategy == "zscore":
        return zscore_sigmoid(scores)
    return minmax(scores)
