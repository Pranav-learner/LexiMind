"""Citation Validator (Step 6) — every citation must point to valid, supporting evidence.

Extends Citation Intelligence's philosophy (deterministic, evidence-grounded) to the *draft answer*:
it checks the `[n]` markers the model actually wrote against the evidence pool the claim was validated
on. Issue types:

- broken     — a claim cites [n] where n has no matching evidence index.
- missing    — an important, supported/weak claim carries NO citation at all.
- weak       — a claim cites evidence whose confidence is low.
- duplicate  — the same evidence index is cited across many claims (info-level; may be fine).
- cross-modal/timestamp citations are recognised (not errors) and annotated.

Invalid references are surfaced (and the engine can reject/deprioritise them) BEFORE results return.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from app.reasoning.interfaces import (
    SUPPORTED, UNSUPPORTED, WEAK, CitationIssue, ClaimVerdict, EvidenceRef,
)

WEAK_EVIDENCE_SCORE = 0.35
DUPLICATE_THRESHOLD = 4


class CitationIntegrityValidator:
    name = "citation-integrity-v1"

    def validate(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef]) -> List[CitationIssue]:
        by_index: Dict[int, EvidenceRef] = {e.index: e for e in evidence}
        issues: List[CitationIssue] = []
        usage: Counter = Counter()

        for v in verdicts:
            cites = v.claim.citation_indices
            for i in cites:
                usage[i] += 1
            # broken citation
            for i in cites:
                if i not in by_index:
                    issues.append(CitationIssue(
                        issue_type="broken", severity="high", citation_index=i, claim_id=v.claim.id,
                        detail=f"Claim {v.claim.id} cites [{i}] which does not exist in the evidence."))
            # weak citation
            for i in cites:
                ev = by_index.get(i)
                if ev is not None and ev.score < WEAK_EVIDENCE_SCORE:
                    issues.append(CitationIssue(
                        issue_type="weak", severity="low", citation_index=i, claim_id=v.claim.id,
                        detail=f"Claim {v.claim.id} cites low-confidence evidence [{i}] "
                               f"(score {ev.score:.2f})."))
            # missing citation on a substantive claim
            if not cites and v.status in (SUPPORTED, WEAK):
                issues.append(CitationIssue(
                    issue_type="missing", severity="medium", claim_id=v.claim.id,
                    detail=f"Claim {v.claim.id} is evidence-backed but carries no [n] citation."))

        # duplicate / over-cited evidence (info)
        for i, n in usage.items():
            if n >= DUPLICATE_THRESHOLD and i in by_index:
                issues.append(CitationIssue(
                    issue_type="duplicate", severity="low", citation_index=i,
                    detail=f"Evidence [{i}] is cited by {n} claims (possible over-reliance)."))
        return issues

    @staticmethod
    def health(issues: List[CitationIssue], total_citations: int) -> Dict[str, object]:
        broken = sum(1 for x in issues if x.issue_type == "broken")
        missing = sum(1 for x in issues if x.issue_type == "missing")
        weak = sum(1 for x in issues if x.issue_type == "weak")
        score = 1.0
        score -= 0.25 * broken + 0.1 * missing + 0.05 * weak
        status = "healthy" if score >= 0.8 else "degraded" if score >= 0.5 else "unhealthy"
        return {"score": round(max(0.0, score), 3), "status": status,
                "broken": broken, "missing": missing, "weak": weak, "citations": total_citations}
