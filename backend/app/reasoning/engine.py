"""Reasoning Engine (Step 2) — the orchestrator of the verification pipeline.

Runs the fixed, interface-driven sequence and assembles the `VerificationReport`:

    claim extraction → evidence validation → contradiction detection → citation validation
    → confidence estimation → self review → explanation → status

It owns NO retrieval and NO generation: it consumes the evidence retrieval already produced and, only
in `thorough` mode, makes ONE optional pass through the single `answer_fn` (for the model critique).
Every stage is injectable (defaults are the deterministic implementations) so a future NLI/LLM backend
swaps in without touching this file. A content-addressed cache skips re-verifying an identical
(answer, evidence, mode) triple (Step 14).
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from app.reasoning.citation_validator import CitationIntegrityValidator
from app.reasoning.claims import SentenceClaimExtractor
from app.reasoning.confidence import SignalConfidenceEngine
from app.reasoning.contradiction import HeuristicContradictionDetector
from app.reasoning.evidence_validator import LexicalEvidenceValidator
from app.reasoning.explanation import StructuredExplanationGenerator
from app.reasoning.interfaces import (
    CONFLICTING, STATUS_FAILED, STATUS_VERIFIED, STATUS_WARNING, SUPPORTED, UNSUPPORTED, WEAK,
    EvidenceRef, VerificationReport,
)
from app.reasoning.self_review import SelfReviewEngine, recommendations_from

_MODALITY = {"transcript": "audio", "speaker": "audio", "subtitle": "audio", "chapter": "timeline",
             "topic": "timeline", "event": "timeline", "scene": "video", "frame": "video",
             "image": "image", "diagram": "diagram", "ocr": "ocr", "table": "document"}


def to_evidence_refs(items: List[Any]) -> List[EvidenceRef]:
    """Normalize Module-2 `Evidence` objects OR raw citation/evidence dicts into `EvidenceRef`s.

    Keeps the engine decoupled from the agents package: validators only ever see `EvidenceRef`.
    """
    refs: List[EvidenceRef] = []
    for i, it in enumerate(items or [], start=1):
        if isinstance(it, EvidenceRef):
            refs.append(it); continue
        if isinstance(it, dict):
            st = it.get("source_type") or it.get("modality") or "text"
            refs.append(EvidenceRef(
                index=int(it.get("index") or i), text=(it.get("text") or it.get("content") or "").strip(),
                source_type=st, document_id=it.get("document_id"), title=it.get("title"),
                page_number=it.get("page_number"), timespan=it.get("timespan"),
                speaker_label=it.get("speaker_label"),
                score=float(it.get("score") or it.get("confidence") or 0.5),
                modality=_MODALITY.get(st, "document")))
        else:  # a Module-2 Evidence dataclass (duck-typed)
            st = getattr(it, "source_type", "text")
            refs.append(EvidenceRef(
                index=int(getattr(it, "index", i)), text=(getattr(it, "text", "") or "").strip(),
                source_type=st, document_id=getattr(it, "document_id", None),
                title=getattr(it, "title", None), page_number=getattr(it, "page_number", None),
                timespan=getattr(it, "timespan", None), speaker_label=getattr(it, "speaker_label", None),
                score=float(getattr(it, "score", 0.5)), modality=_MODALITY.get(st, "document")))
    # drop empties, THEN re-index densely so [n] markers are stable/valid
    refs = [r for r in refs if r.text]
    for n, r in enumerate(refs, start=1):
        r.index = n
    return refs


class _LRU(OrderedDict):
    def __init__(self, cap: int = 128):
        super().__init__(); self.cap = cap

    def put(self, key, val):
        self[key] = val
        self.move_to_end(key)
        while len(self) > self.cap:
            self.popitem(last=False)


class ReasoningEngine:
    def __init__(self, *, extractor=None, validator=None, detector=None, confidence=None,
                 citations=None, reviewer=None, explainer=None, cache: Optional[_LRU] = None):
        self.extractor = extractor or SentenceClaimExtractor()
        self.validator = validator or LexicalEvidenceValidator()
        self.detector = detector or HeuristicContradictionDetector()
        self.confidence = confidence or SignalConfidenceEngine()
        self.citations = citations or CitationIntegrityValidator()
        self.reviewer = reviewer or SelfReviewEngine()
        self.explainer = explainer or StructuredExplanationGenerator()
        self._cache = cache if cache is not None else _CONTENT_CACHE

    def verify(self, *, answer_text: str, evidence: List[Any], mode: str = "fast",
               signals: Optional[Dict[str, Any]] = None, answer_fn=None,
               use_cache: bool = True) -> VerificationReport:
        refs = to_evidence_refs(evidence)
        key = self._key(answer_text, refs, mode)
        if use_cache and mode != "thorough" and key in self._cache:
            return self._cache[key]

        t0 = time.perf_counter()
        timings: Dict[str, float] = {}

        t = time.perf_counter()
        claims = self.extractor.extract(answer_text or "")
        timings["extract_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        verdicts = self.validator.validate(claims, refs)
        timings["validate_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        contradictions = self.detector.detect(verdicts, refs)
        timings["contradiction_ms"] = (time.perf_counter() - t) * 1000

        citation_issues = self.citations.validate(verdicts, refs)
        confidence = self.confidence.estimate(verdicts, refs, contradictions, signals or {})

        report = VerificationReport(
            status=STATUS_WARNING, confidence=confidence, claim_verdicts=verdicts,
            contradictions=contradictions, citation_issues=citation_issues,
            missing_evidence=[v.claim.text for v in verdicts if v.status == UNSUPPORTED],
            evidence=refs, mode=mode)
        report.warnings = self._warnings(report)

        t = time.perf_counter()
        report.review_notes = self.reviewer.review(
            report, answer_text=answer_text or "",
            answer_fn=answer_fn if mode == "thorough" else None,
            depth="thorough" if mode == "thorough" else "fast")
        timings["review_ms"] = (time.perf_counter() - t) * 1000

        report.recommendations = recommendations_from(report)
        report.explanations = self.explainer.explain(report)
        report.status = self._status(report)
        timings["total_ms"] = (time.perf_counter() - t0) * 1000
        report.timings = {k: round(v, 3) for k, v in timings.items()}

        if use_cache and mode != "thorough":
            self._cache.put(key, report)
        return report

    # ------------------------------------------------------------------ status / warnings
    @staticmethod
    def _status(report: VerificationReport) -> str:
        c = report.counts
        n = max(1, len(report.claim_verdicts))
        unsupported_ratio = c[UNSUPPORTED] / n
        high_contra = any(x.severity == "high" for x in report.contradictions)
        broken = any(i.issue_type == "broken" for i in report.citation_issues)
        conf = report.confidence.overall
        if high_contra or c[CONFLICTING] > 0 or unsupported_ratio > 0.5 or conf < 0.4:
            return STATUS_FAILED
        if conf < 0.7 or report.contradictions or c[UNSUPPORTED] > 0 or broken or report.citation_issues:
            return STATUS_WARNING
        return STATUS_VERIFIED

    @staticmethod
    def _warnings(report: VerificationReport) -> List[str]:
        w: List[str] = []
        c = report.counts
        if c[UNSUPPORTED]:
            w.append(f"{c[UNSUPPORTED]} unsupported claim(s).")
        if c[CONFLICTING]:
            w.append(f"{c[CONFLICTING]} claim(s) conflict with evidence.")
        hi = sum(1 for x in report.contradictions if x.severity == "high")
        if hi:
            w.append(f"{hi} high-severity contradiction(s).")
        broken = sum(1 for i in report.citation_issues if i.issue_type == "broken")
        if broken:
            w.append(f"{broken} broken citation(s).")
        if report.confidence.overall < 0.5:
            w.append(f"Low overall confidence ({report.confidence.overall:.0%}).")
        if not report.evidence:
            w.append("No evidence available to verify the answer.")
        return w

    @staticmethod
    def _key(answer_text: str, refs: List[EvidenceRef], mode: str) -> str:
        h = hashlib.sha1()
        h.update((mode + "\x00" + (answer_text or "")).encode("utf-8", "ignore"))
        for r in refs:
            h.update(("\x01" + str(r.index) + r.text).encode("utf-8", "ignore"))
        return h.hexdigest()


_CONTENT_CACHE = _LRU(256)
