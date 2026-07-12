"""Explanation Engine (Step 8) — structured, machine-readable reasoning metadata.

Mirrors Citation Intelligence's deterministic `explain` style: because the verification path is fixed
and every decision is backed by stored signals, an honest explanation is COMPOSED from those signals —
no second LLM call and, importantly, NO chain-of-thought. It exposes *why* (evidence selection,
confidence assignment, contradiction detection, citation acceptance/rejection) as structured data, not
the model's internal deliberation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.reasoning.interfaces import SUPPORTED, VerificationReport

# The fixed verification path — surfaced so developers see how a verdict was reached.
VERIFICATION_PATH = [
    "Claim extraction (segment the draft into checkable statements)",
    "Evidence validation (lexical coverage of each claim by retrieved evidence)",
    "Contradiction detection (polarity/number clashes across sources + claims)",
    "Citation validation (broken / missing / weak / duplicate references)",
    "Confidence estimation (weighted measurable signals)",
    "Self review (deterministic + optional single model critique)",
]


class StructuredExplanationGenerator:
    name = "structured-v1"

    def explain(self, report: VerificationReport) -> Dict[str, Any]:
        return {
            "verification_path": VERIFICATION_PATH,
            "evidence_selection": self._evidence(report),
            "confidence": self._confidence(report),
            "contradictions": self._contradictions(report),
            "citations": self._citations(report),
        }

    @staticmethod
    def _evidence(report: VerificationReport) -> Dict[str, Any]:
        return {
            "summary": (f"{len(report.evidence)} evidence item(s) from retrieval were checked against "
                        f"{len(report.claim_verdicts)} extracted claim(s)."),
            "why_selected": ("Evidence was produced by the fixed Phase-1/4/5 retrieval pipeline (hybrid "
                             "retrieval → fusion → rerank → dedup) and ranked by its retrieval score; "
                             "the validator matched each claim to its best-covering evidence."),
            "top_evidence": [e.to_dict() for e in sorted(report.evidence, key=lambda x: x.score,
                                                          reverse=True)[:5]],
        }

    @staticmethod
    def _confidence(report: VerificationReport) -> Dict[str, Any]:
        c = report.confidence
        return {"overall": c.overall, "band": c.band, "explanation": c.explanation,
                "signals": [s.to_dict() for s in c.signals],
                "how": "overall = Σ (signal value × weight); signals are measured, not model-reported."}

    @staticmethod
    def _contradictions(report: VerificationReport) -> List[Dict[str, Any]]:
        return [{"description": x.description, "reason": x.reason, "severity": x.severity,
                 "why": ("The two texts share subject keywords but disagree in "
                         f"{x.reason} — a deterministic conflict signal.")} for x in report.contradictions]

    @staticmethod
    def _citations(report: VerificationReport) -> Dict[str, Any]:
        accepted = sum(1 for v in report.claim_verdicts
                       if v.claim.citation_indices and v.status == SUPPORTED)
        rejected = [{"index": i.citation_index, "reason": i.issue_type, "detail": i.detail}
                    for i in report.citation_issues if i.issue_type in ("broken", "weak")]
        return {"accepted_grounded": accepted, "rejected_or_flagged": rejected,
                "why": ("A citation is accepted when its evidence exists and overlaps the claim; it is "
                        "flagged when broken (no such evidence), weak (low-confidence evidence), or "
                        "missing on a substantive claim.")}
