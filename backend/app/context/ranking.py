"""Evidence ranking (Phase 2, Task 3).

Retrieval/rerank already produce an ordering, but it's based purely on a model score. For
*context* we want a blended notion of how much a chunk will actually help answer THIS query,
combining several signals:

  - retrieval/reranker score   (the model's relevance judgment)         — primary
  - metadata relevance         (query keywords appearing in section/topic/text)
  - citation confidence        (can we attribute it precisely? complete citation => trust)

The blend is a transparent weighted sum of normalized signals, so it's explainable and
tunable — not a black box. The result sets `evidence_score`, which downstream stages
(dedup survivor selection, budget prioritization, assembly order) all rely on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence

from app.context.schemas import Citation, Evidence

_WORD_RE = re.compile(r"[a-z0-9]+")


def _minmax_normalize(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 for _ in values]  # all equal -> neutral 1.0
    return [(v - lo) / (hi - lo) for v in values]


def _citation_confidence(citations: List[Citation]) -> float:
    if not citations:
        return 0.0
    return sum(1.0 if c.is_complete() else 0.5 for c in citations) / len(citations)


@dataclass
class EvidenceRanker:
    # Weights sum is arbitrary; only relative magnitudes matter.
    retrieval_weight: float = 0.6
    metadata_weight: float = 0.25
    citation_weight: float = 0.15

    def _metadata_relevance(self, ev: Evidence, query_keywords: Sequence[str]) -> float:
        if not query_keywords:
            return 0.5  # neutral when we have no keywords to match on
        kw = set(query_keywords)
        haystack = " ".join(
            str(ev.chunk.metadata.get(k, "") or "") for k in ("section", "topic", "section_heading")
        )
        section_tokens = set(_WORD_RE.findall(haystack.lower()))
        text_tokens = set(_WORD_RE.findall(ev.text.lower()))
        # Section/topic matches weigh more than body matches (they signal aboutness).
        section_hits = len(kw & section_tokens) / len(kw)
        text_hits = len(kw & text_tokens) / len(kw)
        return min(1.0, 0.6 * section_hits + 0.4 * text_hits)

    def rank(self, evidence: List[Evidence], query_keywords: Sequence[str]) -> List[Evidence]:
        if not evidence:
            return []

        norm_retrieval = _minmax_normalize([e.retrieval_score for e in evidence])
        for ev, r in zip(evidence, norm_retrieval):
            meta_rel = self._metadata_relevance(ev, query_keywords)
            cite_conf = _citation_confidence(ev.citations)
            ev.evidence_score = (
                self.retrieval_weight * r
                + self.metadata_weight * meta_rel
                + self.citation_weight * cite_conf
            )

        evidence.sort(key=lambda e: e.evidence_score, reverse=True)
        return evidence
