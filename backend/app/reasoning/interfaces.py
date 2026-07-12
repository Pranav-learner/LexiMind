"""Verification & Reasoning interfaces (Phase 6, Module 3) — the interface-driven trust layer.

Every stage of verification is a small Protocol operating on plain, serializable value objects, so a
future reasoning backend (an NLI model, an LLM judge, an embedding-based validator) drops in WITHOUT
touching the engine. The engine depends on these abstractions, never on a concrete implementation.

Value objects (dataclasses, all `to_dict`):
- `EvidenceRef`   — a normalized, engine-internal view of one piece of evidence (from a Module-2
                    `Evidence` object OR a raw citation/dict), so validators never import agents.
- `Claim`         — one important statement extracted from the draft answer (+ its [n] citation refs).
- `ClaimVerdict`  — the validator's ruling on a claim (supported/weak/unsupported/conflicting + why).
- `Contradiction` — a detected conflict (claim↔evidence or evidence↔evidence) + severity.
- `CitationIssue` — a citation problem (broken/missing/duplicate/weak) + detail.
- `ConfidenceSignal` / `ConfidenceBreakdown` — measurable system signals → an overall/section/claim score.
- `VerificationReport` — the structured report that accompanies every agent execution.

Protocols: ClaimExtractor · EvidenceValidator · ContradictionDetector · ConfidenceEngine ·
CitationValidator · SelfReviewer · ExplanationGenerator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

# claim / evidence status vocabularies (fixed strings so a persistent/UI layer can rely on them)
SUPPORTED = "supported"
WEAK = "weakly_supported"
UNSUPPORTED = "unsupported"
CONFLICTING = "conflicting"

STATUS_VERIFIED = "verified"
STATUS_WARNING = "warning"
STATUS_FAILED = "failed"


# --------------------------------------------------------------------- value objects
@dataclass
class EvidenceRef:
    index: int
    text: str
    source_type: str = "text"            # text | ocr | image | diagram | transcript | chapter | …
    document_id: Optional[str] = None
    title: Optional[str] = None
    page_number: Optional[int] = None
    timespan: Optional[str] = None
    speaker_label: Optional[str] = None
    score: float = 0.5                    # retrieval/evidence confidence carried from Phase 1/4/5
    modality: str = "document"            # document | image | diagram | ocr | audio | video | timeline

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "text": self.text[:400], "source_type": self.source_type,
                "document_id": self.document_id, "title": self.title, "page_number": self.page_number,
                "timespan": self.timespan, "speaker_label": self.speaker_label,
                "score": round(self.score, 4), "modality": self.modality}


@dataclass
class Claim:
    id: str
    text: str
    section: str = ""
    citation_indices: List[int] = field(default_factory=list)   # [n] markers parsed from the claim
    important: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "text": self.text, "section": self.section,
                "citation_indices": self.citation_indices, "important": self.important}


@dataclass
class ClaimVerdict:
    claim: Claim
    status: str                           # supported | weakly_supported | unsupported | conflicting
    support_score: float                  # 0..1 best evidence coverage
    matched_evidence: List[int] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"claim": self.claim.to_dict(), "status": self.status,
                "support_score": round(self.support_score, 4),
                "matched_evidence": self.matched_evidence, "rationale": self.rationale}


@dataclass
class Contradiction:
    kind: str                             # claim_vs_evidence | evidence_vs_evidence
    severity: str                         # high | medium | low
    description: str
    left: str = ""                        # the two conflicting texts (truncated)
    right: str = ""
    left_ref: Optional[int] = None         # evidence index / claim index for UI linking
    right_ref: Optional[int] = None
    reason: str = ""                      # polarity | numeric | antonym

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity, "description": self.description,
                "left": self.left[:240], "right": self.right[:240], "left_ref": self.left_ref,
                "right_ref": self.right_ref, "reason": self.reason}


@dataclass
class CitationIssue:
    issue_type: str                       # broken | missing | duplicate | weak | ok
    detail: str
    citation_index: Optional[int] = None
    claim_id: Optional[str] = None
    severity: str = "medium"              # high | medium | low

    def to_dict(self) -> Dict[str, Any]:
        return {"issue_type": self.issue_type, "detail": self.detail,
                "citation_index": self.citation_index, "claim_id": self.claim_id,
                "severity": self.severity}


@dataclass
class ConfidenceSignal:
    name: str
    value: float                          # 0..1
    weight: float                         # 0..1 (weights sum to 1)
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.value * self.weight

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": round(self.value, 4), "weight": round(self.weight, 4),
                "contribution": round(self.contribution, 4), "detail": self.detail}


@dataclass
class ConfidenceBreakdown:
    overall: float
    band: str                             # high | moderate | low
    signals: List[ConfidenceSignal] = field(default_factory=list)
    per_section: Dict[str, float] = field(default_factory=dict)
    per_claim: Dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"overall": round(self.overall, 4), "band": self.band,
                "signals": [s.to_dict() for s in self.signals],
                "per_section": {k: round(v, 4) for k, v in self.per_section.items()},
                "per_claim": {k: round(v, 4) for k, v in self.per_claim.items()},
                "explanation": self.explanation}


@dataclass
class VerificationReport:
    status: str                           # verified | warning | failed
    confidence: ConfidenceBreakdown
    claim_verdicts: List[ClaimVerdict] = field(default_factory=list)
    contradictions: List[Contradiction] = field(default_factory=list)
    citation_issues: List[CitationIssue] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)   # claim texts with no support
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    explanations: Dict[str, Any] = field(default_factory=dict)
    review_notes: List[str] = field(default_factory=list)        # self-review (deterministic + optional LLM)
    evidence: List[EvidenceRef] = field(default_factory=list)
    mode: str = "fast"
    timings: Dict[str, float] = field(default_factory=dict)

    # --- rollup counts (computed) ---
    @property
    def counts(self) -> Dict[str, int]:
        c = {SUPPORTED: 0, WEAK: 0, UNSUPPORTED: 0, CONFLICTING: 0}
        for v in self.claim_verdicts:
            c[v.status] = c.get(v.status, 0) + 1
        return c

    def to_dict(self) -> Dict[str, Any]:
        c = self.counts
        return {
            "status": self.status, "mode": self.mode,
            "confidence": self.confidence.to_dict(),
            "claims_total": len(self.claim_verdicts),
            "counts": c,
            "supported_ratio": round(c[SUPPORTED] / len(self.claim_verdicts), 4) if self.claim_verdicts else 0.0,
            "claim_verdicts": [v.to_dict() for v in self.claim_verdicts],
            "contradictions": [x.to_dict() for x in self.contradictions],
            "citation_issues": [x.to_dict() for x in self.citation_issues],
            "missing_evidence": self.missing_evidence,
            "warnings": self.warnings, "recommendations": self.recommendations,
            "review_notes": self.review_notes, "explanations": self.explanations,
            "evidence": [e.to_dict() for e in self.evidence], "timings": self.timings,
        }


# --------------------------------------------------------------------- protocols
class ClaimExtractor(Protocol):
    def extract(self, answer_text: str, *, sections: Optional[Dict[str, str]] = None) -> List[Claim]: ...


class EvidenceValidator(Protocol):
    def validate(self, claims: List[Claim], evidence: List[EvidenceRef]) -> List[ClaimVerdict]: ...


class ContradictionDetector(Protocol):
    def detect(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef]) -> List[Contradiction]: ...


class ConfidenceEngine(Protocol):
    def estimate(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef],
                 contradictions: List[Contradiction], signals_in: Dict[str, Any]) -> ConfidenceBreakdown: ...


class CitationValidator(Protocol):
    def validate(self, verdicts: List[ClaimVerdict], evidence: List[EvidenceRef]) -> List[CitationIssue]: ...


class SelfReviewer(Protocol):
    def review(self, report: "VerificationReport", *, answer_text: str, answer_fn=None,
               depth: str = "fast") -> List[str]: ...


class ExplanationGenerator(Protocol):
    def explain(self, report: "VerificationReport") -> Dict[str, Any]: ...
