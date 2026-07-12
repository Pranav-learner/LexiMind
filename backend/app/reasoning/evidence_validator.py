"""Evidence Validator (Step 3) — verify every important claim against retrieved evidence.

For each claim it measures lexical support against the evidence pool (reusing the same evidence the
retrieval pipeline already produced — NO new retrieval) and classifies it:

- supported            — strong keyword coverage by some evidence (or a valid citation with real overlap).
- weakly_supported     — partial coverage; the gist is present but thin.
- unsupported          — no evidence covers the claim.
- conflicting          — evidence overlaps the claim's subject but disagrees in polarity/number.

Works across ALL evidence modalities (document/image/diagram/OCR/audio/video/timeline) because it
operates on the normalized `EvidenceRef.text` each modality already contributes. A cited [n] that
actually overlaps is treated as first-class support (rewarded); a cited [n] with no overlap is a
citation problem surfaced later by the CitationValidator.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.reasoning.interfaces import (
    CONFLICTING, SUPPORTED, UNSUPPORTED, WEAK, Claim, ClaimVerdict, EvidenceRef,
)
from app.reasoning.textutil import coverage, numeric_conflict, polarity_conflict

# thresholds — deliberately explicit so they're tunable + testable
SUPPORT_STRONG = 0.6
SUPPORT_WEAK = 0.3
OVERLAP_FOR_CONFLICT = 0.35   # need real subject overlap before calling a polarity/number clash a conflict


class LexicalEvidenceValidator:
    name = "lexical-v1"

    def __init__(self, *, cache: Dict = None):
        # memoize (claim_text, evidence_index) coverage so re-verification of identical evidence is cheap
        self._cache: Dict[Tuple[str, int], float] = cache if cache is not None else {}

    def validate(self, claims: List[Claim], evidence: List[EvidenceRef]) -> List[ClaimVerdict]:
        return [self._validate_one(c, evidence) for c in claims]

    def _validate_one(self, claim: Claim, evidence: List[EvidenceRef]) -> ClaimVerdict:
        if not evidence:
            return ClaimVerdict(claim=claim, status=UNSUPPORTED, support_score=0.0,
                                rationale="No evidence was available to check this claim.")
        scored: List[Tuple[float, EvidenceRef]] = []
        for ev in evidence:
            key = (claim.text, ev.index)
            cov = self._cache.get(key)
            if cov is None:
                cov = coverage(claim.text, ev.text)
                self._cache[key] = cov
            scored.append((cov, ev))
        scored.sort(key=lambda t: t[0], reverse=True)
        best_cov, best_ev = scored[0]

        # a valid citation that genuinely overlaps gets a small credit (rewards grounded citing)
        cited = set(claim.citation_indices)
        cite_bonus = 0.0
        if cited:
            for cov, ev in scored:
                if ev.index in cited and cov >= SUPPORT_WEAK:
                    cite_bonus = 0.1
                    break
        support = min(1.0, best_cov + cite_bonus)

        matched = [ev.index for cov, ev in scored if cov >= SUPPORT_WEAK][:5]

        # conflict: a well-overlapping piece of evidence disagrees in polarity or numbers
        for cov, ev in scored:
            if cov >= OVERLAP_FOR_CONFLICT and (
                polarity_conflict(claim.text, ev.text) or numeric_conflict(claim.text, ev.text)
            ):
                reason = "polarity" if polarity_conflict(claim.text, ev.text) else "numeric"
                return ClaimVerdict(claim=claim, status=CONFLICTING, support_score=round(support, 4),
                                    matched_evidence=[ev.index],
                                    rationale=f"Evidence [{ev.index}] overlaps the claim but disagrees "
                                              f"({reason}).")

        if support >= SUPPORT_STRONG:
            status, why = SUPPORTED, f"Evidence [{best_ev.index}] covers {best_cov:.0%} of the claim."
        elif support >= SUPPORT_WEAK:
            status, why = WEAK, f"Only partial support (best coverage {best_cov:.0%})."
        else:
            status, why = UNSUPPORTED, "No evidence meaningfully covers this claim."
        return ClaimVerdict(claim=claim, status=status, support_score=round(support, 4),
                            matched_evidence=matched, rationale=why)
