"""Temporal reranking (Step 6) — unified, time-aware relevance re-scoring of fused results.

Generalizes the mmretrieval cross-modal reranker to (query, ANY temporal signal) behind a
`TemporalReranker` interface. The default `LexicalTemporalReranker` is pure/deterministic (testable
without torch): relevance = query↔(title+content) overlap, blended with temporal priors —
  - primary-intent modality match,
  - speaker match when the query names a speaker,
  - time-anchor proximity (already captured as `proximity_bonus`).
`CrossEncoderTemporalReranker` (lazy) reuses the Phase-1 cross-encoder with the same blending.
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from app.tretrieval.retrievers import lexical_score
from app.tretrieval.schemas import TemporalHit

_MODALITY_PRIOR = 0.15
_SPEAKER_PRIOR = 0.2


class TemporalReranker(Protocol):
    def rerank(self, query: str, keywords: List[str], hits: List[TemporalHit], *,
               primary: str, speaker_hint: Optional[str] = None) -> List[TemporalHit]: ...


class LexicalTemporalReranker:
    def rerank(self, query: str, keywords: List[str], hits: List[TemporalHit], *,
               primary: str, speaker_hint: Optional[str] = None) -> List[TemporalHit]:
        if not hits:
            return hits
        raw = []
        for h in hits:
            r = lexical_score(keywords, [(h.title, 1.2), (h.content, 1.0)])
            if h.modality == primary:
                r += _MODALITY_PRIOR * (r + 1.0)
            if speaker_hint and speaker_hint.lower() in (h.speaker_label or "").lower():
                r += _SPEAKER_PRIOR * (r + 1.0)
            r += h.proximity_bonus  # time-anchor proximity carries through rerank
            raw.append(r)
        hi = max(raw) if raw else 0.0
        for h, r in zip(hits, raw):
            h.reranker_score = round((r / hi) if hi > 1e-9 else 0.0, 6)
        return self._blend_and_sort(hits)

    @staticmethod
    def _blend_and_sort(hits: List[TemporalHit]) -> List[TemporalHit]:
        fmax = max((h.fusion_score for h in hits), default=0.0)
        for h in hits:
            fnorm = (h.fusion_score / fmax) if fmax > 1e-9 else 0.0
            rel = h.reranker_score if h.reranker_score is not None else 0.0
            h.confidence = round(0.5 * fnorm + 0.5 * rel, 4)
        ranked = sorted(hits, key=lambda h: (h.confidence, h.fusion_score), reverse=True)
        for i, h in enumerate(ranked, start=1):
            h.final_rank = i
        return ranked


class CrossEncoderTemporalReranker:
    """Production temporal reranker (lazy). Reuses the Phase-1 cross-encoder over each hit's text."""

    def rerank(self, query, keywords, hits, *, primary, speaker_hint=None):  # pragma: no cover
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
                base += h.proximity_bonus * 0.1
                h.reranker_score = round(float(base), 6)
            return LexicalTemporalReranker._blend_and_sort(hits)
        except Exception:
            return LexicalTemporalReranker().rerank(query, keywords, hits, primary=primary,
                                                    speaker_hint=speaker_hint)


def no_rerank(hits: List[TemporalHit]) -> List[TemporalHit]:
    fmax = max((h.fusion_score for h in hits), default=0.0)
    for h in hits:
        h.confidence = round((h.fusion_score / fmax) if fmax > 1e-9 else 0.0, 4)
    return hits
