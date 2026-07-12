"""Contradiction Detector (Step 4) — surface conflicts within the evidence and against the draft.

Two families, both deterministic:
- claim_vs_evidence   — a claim ruled `conflicting` by the evidence validator (evidence overlaps the
                        claim's subject but disagrees in polarity/number).
- evidence_vs_evidence— two retrieved sources cover the same subject (keyword overlap) but disagree in
                        polarity (negation parity / antonyms) or numbers. This spans modalities and
                        sources (document↔document, document↔lecture, image↔text, …) because it runs
                        over the normalized evidence pool.

Also reports coarse "missing information / ambiguous evidence" as low-severity signals. A future NLI
model plugs in behind the `ContradictionDetector` protocol.
"""

from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Tuple

from app.reasoning.interfaces import CONFLICTING, Contradiction, ClaimVerdict, EvidenceRef
from app.reasoning.textutil import jaccard, numeric_conflict, polarity_conflict

SUBJECT_OVERLAP = 0.3          # min keyword overlap before two evidences are "about the same thing"
MAX_PAIRS = 400                # cap pairwise checks on very large evidence pools (perf guard)


class HeuristicContradictionDetector:
    name = "heuristic-v1"

    def __init__(self, *, cache: Dict = None):
        self._cache: Dict[Tuple[int, int], bool] = cache if cache is not None else {}

    def detect(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef]) -> List[Contradiction]:
        out: List[Contradiction] = []

        # 1) claim vs evidence — promote conflicting verdicts to contradictions
        for v in verdicts:
            if v.status == CONFLICTING:
                ref = v.matched_evidence[0] if v.matched_evidence else None
                ev_text = next((e.text for e in evidence if e.index == ref), "")
                out.append(Contradiction(
                    kind="claim_vs_evidence", severity="high",
                    description=f"Claim conflicts with evidence [{ref}].",
                    left=v.claim.text, right=ev_text, right_ref=ref, reason=v.rationale.split("(")[-1].rstrip(").")))

        # 2) evidence vs evidence — pairwise polarity/number clash among same-subject sources
        pairs = 0
        for a, b in combinations(evidence, 2):
            if pairs >= MAX_PAIRS:
                break
            pairs += 1
            key = (a.index, b.index)
            if key not in self._cache:
                same_subject = jaccard(a.text, b.text) >= SUBJECT_OVERLAP
                self._cache[key] = bool(
                    same_subject and (polarity_conflict(a.text, b.text) or numeric_conflict(a.text, b.text)))
            if self._cache[key]:
                reason = "numeric" if numeric_conflict(a.text, b.text) else "polarity"
                cross = a.document_id != b.document_id
                out.append(Contradiction(
                    kind="evidence_vs_evidence", severity="medium" if cross else "low",
                    description=(f"Sources [{a.index}] and [{b.index}] disagree ({reason})"
                                + (" across documents." if cross else " within a source.")),
                    left=a.text, right=b.text, left_ref=a.index, right_ref=b.index, reason=reason))
        return out

    @staticmethod
    def ambiguities(verdicts: List[ClaimVerdict]) -> List[str]:
        """Coarse 'missing / ambiguous evidence' notes (low severity)."""
        weak = [v for v in verdicts if v.status in ("weakly_supported",)]
        notes = []
        if weak:
            notes.append(f"{len(weak)} claim(s) have only weak/ambiguous evidence.")
        return notes
