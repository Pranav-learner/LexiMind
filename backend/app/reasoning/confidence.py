"""Confidence Engine (Step 5) — estimate confidence from MEASURABLE SYSTEM SIGNALS, not LLM self-report.

Confidence is a weighted blend of signals the platform can actually measure:
- support_ratio          — fraction of claims the evidence validator ruled supported.
- retrieval_quality      — mean retrieval/evidence score carried from Phase 1/4/5.
- citation_coverage      — fraction of claims that carry a valid, overlapping citation.
- cross_source_agreement — 1 − contradiction penalty.
- evidence_sufficiency   — enough distinct evidence for the number of claims.
- execution_success      — agent/tool success signals passed in from the run.

Each signal ∈ [0,1] with a fixed weight (weights sum to 1); `overall = Σ value·weight`. The breakdown
also rolls up per-section and per-claim confidence, and produces a plain-language explanation. This
never asks the model "how confident are you" — it reports what the evidence + execution support.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List

from app.reasoning.interfaces import (
    CONFLICTING, SUPPORTED, UNSUPPORTED, WEAK, ClaimVerdict, ConfidenceBreakdown, ConfidenceSignal,
    Contradiction, EvidenceRef,
)

# signal weights (sum = 1.0)
WEIGHTS = {
    "support_ratio": 0.30,
    "retrieval_quality": 0.18,
    "citation_coverage": 0.18,
    "cross_source_agreement": 0.15,
    "evidence_sufficiency": 0.12,
    "execution_success": 0.07,
}


def _band(x: float) -> str:
    return "high" if x >= 0.75 else "moderate" if x >= 0.5 else "low"


class SignalConfidenceEngine:
    name = "signals-v1"

    def estimate(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef],
                 contradictions: List[Contradiction], signals_in: Dict[str, Any]) -> ConfidenceBreakdown:
        n = len(verdicts)
        valid_idx = {e.index for e in evidence}
        supported = sum(1 for v in verdicts if v.status == SUPPORTED)
        weak = sum(1 for v in verdicts if v.status == WEAK)
        # a claim "carries a valid citation" if it cites a real evidence index and is at least weakly supported
        cited_ok = sum(1 for v in verdicts
                       if v.status in (SUPPORTED, WEAK)
                       and any(i in valid_idx for i in v.claim.citation_indices))

        support_ratio = (supported + 0.4 * weak) / n if n else (0.5 if evidence else 0.0)
        retrieval_quality = mean([e.score for e in evidence]) if evidence else 0.0
        citation_coverage = cited_ok / n if n else 0.0
        hi = sum(1 for c in contradictions if c.severity == "high")
        med = sum(1 for c in contradictions if c.severity == "medium")
        cross_source_agreement = max(0.0, 1.0 - (0.4 * hi + 0.15 * med))
        evidence_sufficiency = min(1.0, len(evidence) / max(1, min(n, 6))) if n else min(1.0, len(evidence) / 4)
        execution_success = float(signals_in.get("execution_success", 1.0 if signals_in.get("success", True) else 0.3))

        raw = {
            "support_ratio": support_ratio, "retrieval_quality": retrieval_quality,
            "citation_coverage": citation_coverage, "cross_source_agreement": cross_source_agreement,
            "evidence_sufficiency": evidence_sufficiency, "execution_success": execution_success,
        }
        details = {
            "support_ratio": f"{supported}/{n} claims supported" + (f", {weak} weak" if weak else ""),
            "retrieval_quality": f"mean evidence score {retrieval_quality:.2f} over {len(evidence)} item(s)",
            "citation_coverage": f"{cited_ok}/{n} claims carry a valid citation",
            "cross_source_agreement": f"{hi} high + {med} medium contradiction(s)",
            "evidence_sufficiency": f"{len(evidence)} evidence item(s) for {n} claim(s)",
            "execution_success": "agent/tool execution signal",
        }
        signals = [ConfidenceSignal(name=k, value=_clamp(raw[k]), weight=WEIGHTS[k], detail=details[k])
                   for k in WEIGHTS]
        overall = round(sum(s.contribution for s in signals), 4)

        per_section = self._per_section(verdicts)
        per_claim = {v.claim.id: v.support_score for v in verdicts}
        band = _band(overall)
        explanation = (
            f"Confidence is {band} ({overall:.0%}). Strongest signals: "
            + ", ".join(f"{s.name} {s.value:.0%}" for s in sorted(signals, key=lambda s: s.contribution,
                                                                   reverse=True)[:2])
            + (f". Lowered by {hi} high-severity contradiction(s)." if hi else ".")
        )
        return ConfidenceBreakdown(overall=overall, band=band, signals=signals, per_section=per_section,
                                   per_claim=per_claim, explanation=explanation)

    @staticmethod
    def _per_section(verdicts: List[ClaimVerdict]) -> Dict[str, float]:
        buckets: Dict[str, List[float]] = {}
        for v in verdicts:
            buckets.setdefault(v.claim.section or "(body)", []).append(v.support_score)
        return {k: round(mean(vs), 4) for k, vs in buckets.items() if vs}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
