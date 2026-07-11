"""Cross-modal reranking (Step 6) — a unified, modality-aware relevance re-scoring of fused results.

Phase-1 reranked (query, text-chunk) with a cross-encoder. This generalizes to (query, ANY modality)
behind a `CrossModalReranker` interface so the reranker MODEL can evolve without touching business
logic. Two implementations:
- `LexicalCrossModalReranker` (default, pure): query↔content relevance + a modality prior aligned to
  the query intent. Deterministic → testable without torch.
- `CrossEncoderReranker` (production, lazy): wraps the Phase-1 cross-encoder over each hit's textual
  representation (content/caption/table serialization), with the same modality-aware blending.

The reranker sets `reranker_score` and a final `confidence` (a blend of fused rank strength +
relevance) and re-orders; `final_rank` is reassigned by the caller.
"""

from __future__ import annotations

from typing import List, Protocol

from app.mmretrieval.retrievers import lexical_score
from app.mmretrieval.schemas import RetrievalHit


class CrossModalReranker(Protocol):
    def rerank(self, query: str, keywords: List[str], hits: List[RetrievalHit], *, primary: str) -> List[RetrievalHit]: ...


# Small priors: a hit whose modality matches the query's primary intent is nudged up.
_MODALITY_PRIOR = 0.15


class LexicalCrossModalReranker:
    def rerank(self, query: str, keywords: List[str], hits: List[RetrievalHit], *, primary: str) -> List[RetrievalHit]:
        if not hits:
            return hits
        # Relevance = query↔(title+content) lexical overlap, normalized within this result set.
        raw = []
        for h in hits:
            r = lexical_score(keywords, [(h.title, 1.2), (h.content, 1.0)])
            if h.modality == primary:
                r += _MODALITY_PRIOR * (r + 1.0)
            raw.append(r)
        hi = max(raw) if raw else 0.0
        for h, r in zip(hits, raw):
            rel = (r / hi) if hi > 1e-9 else 0.0
            h.reranker_score = round(rel, 6)
        return self._blend_and_sort(hits)

    @staticmethod
    def _blend_and_sort(hits: List[RetrievalHit]) -> List[RetrievalHit]:
        # Normalize fusion score within the set, then blend 50/50 with reranker relevance.
        fmax = max((h.fusion_score for h in hits), default=0.0)
        for h in hits:
            fnorm = (h.fusion_score / fmax) if fmax > 1e-9 else 0.0
            rel = h.reranker_score if h.reranker_score is not None else 0.0
            h.confidence = round(0.5 * fnorm + 0.5 * rel, 4)
        ranked = sorted(hits, key=lambda h: (h.confidence, h.fusion_score), reverse=True)
        for i, h in enumerate(ranked, start=1):
            h.final_rank = i
        return ranked


class CrossEncoderReranker:
    """Production cross-modal reranker (lazy). Reuses the Phase-1 reranker model."""

    def rerank(self, query: str, keywords: List[str], hits: List[RetrievalHit], *, primary: str) -> List[RetrievalHit]:  # pragma: no cover
        try:
            from app.core.state import reranker
            if reranker is None:
                raise RuntimeError("reranker disabled")
            pairs = [(query, f"{h.title} {h.content}".strip()) for h in hits]
            scores = reranker.score(pairs) if hasattr(reranker, "score") else [0.0] * len(hits)
            hi = max(scores) if scores else 0.0
            for h, s in zip(hits, scores):
                base = (s / hi) if hi > 1e-9 else 0.0
                if h.modality == primary:
                    base = min(1.0, base + _MODALITY_PRIOR)
                h.reranker_score = round(float(base), 6)
            return LexicalCrossModalReranker._blend_and_sort(hits)
        except Exception:
            return LexicalCrossModalReranker().rerank(query, keywords, hits, primary=primary)


def no_rerank(hits: List[RetrievalHit]) -> List[RetrievalHit]:
    """When rerank is disabled: confidence = normalized fusion score, keep fusion order."""
    fmax = max((h.fusion_score for h in hits), default=0.0)
    for h in hits:
        h.confidence = round((h.fusion_score / fmax) if fmax > 1e-9 else 0.0, 4)
    return hits
