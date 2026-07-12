"""Unit tests for the Phase-6 Module-3 Verification & Reasoning Engine — pure/offline (no HTTP, no LLM).

Covers the deterministic text primitives, claim extraction, evidence validation, contradiction
detection, confidence estimation, citation validation, self review, explanation, and the engine's
status logic + caching + evidence normalization.
"""

from __future__ import annotations

from app.reasoning.citation_validator import CitationIntegrityValidator
from app.reasoning.claims import SentenceClaimExtractor
from app.reasoning.confidence import SignalConfidenceEngine, WEIGHTS
from app.reasoning.contradiction import HeuristicContradictionDetector
from app.reasoning.engine import ReasoningEngine, to_evidence_refs
from app.reasoning.evidence_validator import LexicalEvidenceValidator
from app.reasoning.explanation import StructuredExplanationGenerator
from app.reasoning.interfaces import (
    CONFLICTING, STATUS_FAILED, STATUS_VERIFIED, STATUS_WARNING, SUPPORTED, UNSUPPORTED, WEAK,
    Claim, ClaimVerdict, EvidenceRef,
)
from app.reasoning.self_review import SelfReviewEngine, recommendations_from
from app.reasoning import textutil as T


# --------------------------------------------------------------------- textutil
def test_coverage_and_jaccard():
    assert T.coverage("mutex mutual exclusion", "a mutex provides mutual exclusion") == 1.0
    assert T.coverage("quantum teleportation", "a mutex provides mutual exclusion") == 0.0
    assert 0 < T.jaccard("paging is reliable", "paging is not reliable") <= 1.0


def test_polarity_and_numeric_conflict():
    assert T.polarity_conflict("TCP is reliable", "TCP is not reliable") is True
    assert T.polarity_conflict("latency increases", "latency decreases") is True
    # incidental negation not attached to a shared keyword → NOT a conflict
    assert T.polarity_conflict("deadlock requires four conditions",
                               "deadlock requires hold and wait, no preemption") is False
    assert T.numeric_conflict("the timeout is 30 seconds", "the timeout is 60 seconds") is True
    assert T.numeric_conflict("the timeout is 30 seconds", "the timeout is 30 seconds") is False


def test_sentences_and_negation():
    assert len(T.sentences("First fact. Second fact! Third?")) == 3
    assert T.has_negation("this is not true") and not T.has_negation("this is true")


# --------------------------------------------------------------------- claim extraction
def test_claim_extraction_parses_citations_and_skips_noise():
    text = ("## Heading\n"
            "A mutex ensures mutual exclusion [1].\n"
            "- Deadlock needs four conditions [2][3].\n"
            "| a | b |\n"
            "Is this a question?\n"
            "```\ncode line\n```\n"
            "ok")   # too short → skipped
    claims = SentenceClaimExtractor().extract(text)
    texts = [c.text for c in claims]
    assert any("mutex" in t for t in texts) and any("Deadlock" in t for t in texts)
    assert all("code line" != t for t in texts) and all(not t.endswith("?") for t in texts)
    deadlock = next(c for c in claims if "Deadlock" in c.text)
    assert deadlock.citation_indices == [2, 3] and deadlock.section == "Heading"


# --------------------------------------------------------------------- evidence validator
def _ev(i, text, score=0.8, doc="d1"):
    return EvidenceRef(index=i, text=text, document_id=doc, score=score)


def test_evidence_validator_statuses():
    v = LexicalEvidenceValidator()
    evidence = [_ev(1, "A mutex provides mutual exclusion for one thread in the critical section")]
    supported = v.validate([Claim(id="c1", text="A mutex provides mutual exclusion", citation_indices=[1])], evidence)[0]
    assert supported.status == SUPPORTED and supported.support_score > 0.6
    unsupported = v.validate([Claim(id="c2", text="Quantum computers instantly solve halting problems")], evidence)[0]
    assert unsupported.status == UNSUPPORTED
    conflicting = v.validate([Claim(id="c3", text="A mutex is not for mutual exclusion")],
                             [_ev(1, "A mutex is for mutual exclusion")])[0]
    assert conflicting.status == CONFLICTING


def test_evidence_validator_empty_pool():
    v = LexicalEvidenceValidator()
    out = v.validate([Claim(id="c1", text="anything at all here")], [])[0]
    assert out.status == UNSUPPORTED and out.support_score == 0.0


# --------------------------------------------------------------------- contradiction detector
def test_contradiction_evidence_vs_evidence():
    d = HeuristicContradictionDetector()
    ev = [_ev(1, "Paging is reliable and prevents fragmentation", doc="d1"),
          _ev(2, "Paging is not reliable in this system", doc="d2")]
    out = d.detect([], ev)
    assert any(c.kind == "evidence_vs_evidence" and c.reason == "polarity" for c in out)
    assert out[0].severity == "medium"           # cross-document


def test_contradiction_claim_vs_evidence():
    d = HeuristicContradictionDetector()
    verdict = ClaimVerdict(claim=Claim(id="c1", text="X is safe"), status=CONFLICTING, support_score=0.5,
                           matched_evidence=[1], rationale="Evidence [1] overlaps but disagrees (polarity).")
    out = d.detect([verdict], [_ev(1, "X is not safe")])
    assert out and out[0].kind == "claim_vs_evidence" and out[0].severity == "high"


# --------------------------------------------------------------------- confidence engine
def test_confidence_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_confidence_estimate():
    eng = SignalConfidenceEngine()
    verdicts = [ClaimVerdict(claim=Claim(id="c1", text="a", citation_indices=[1]), status=SUPPORTED, support_score=0.9, matched_evidence=[1]),
                ClaimVerdict(claim=Claim(id="c2", text="b"), status=UNSUPPORTED, support_score=0.1)]
    c = eng.estimate(verdicts, [_ev(1, "evidence a", score=0.9)], [], {"success": True})
    assert 0.0 <= c.overall <= 1.0 and c.band in ("high", "moderate", "low")
    assert abs(c.overall - sum(s.contribution for s in c.signals)) < 1e-6
    assert "c1" in c.per_claim
    low = eng.estimate([], [], [], {})
    assert low.overall < 0.6


# --------------------------------------------------------------------- citation validator
def test_citation_validator_issues():
    val = CitationIntegrityValidator()
    verdicts = [
        ClaimVerdict(claim=Claim(id="c1", text="cites missing", citation_indices=[9]), status=SUPPORTED, support_score=0.8),
        ClaimVerdict(claim=Claim(id="c2", text="no citation here", citation_indices=[]), status=SUPPORTED, support_score=0.7),
        ClaimVerdict(claim=Claim(id="c3", text="weak cite", citation_indices=[1]), status=WEAK, support_score=0.4),
    ]
    ev = [_ev(1, "low conf evidence", score=0.2)]
    issues = {i.issue_type for i in val.validate(verdicts, ev)}
    assert "broken" in issues and "missing" in issues and "weak" in issues


# --------------------------------------------------------------------- self review + recommendations
def test_self_review_fast_and_thorough():
    r = ReasoningEngine().verify(
        answer_text="Cats can fly to the moon unaided.", evidence=[_ev(1, "Cats are mammals")], mode="fast")
    notes = SelfReviewEngine().review(r, answer_text="x", depth="fast")
    assert any("unsupported" in n for n in notes)
    called = {"n": 0}
    def fake_fn(prompt): called["n"] += 1; return "- issue: unsupported claim"
    notes2 = SelfReviewEngine().review(r, answer_text="x", answer_fn=fake_fn, depth="thorough")
    assert called["n"] == 1 and any("Model review" in n for n in notes2)   # bounded to ONE call


def test_recommendations_from_report():
    r = ReasoningEngine().verify(answer_text="Dragons are real animals living in caves.",
                                 evidence=[_ev(1, "Caves are underground")], mode="fast")
    recs = recommendations_from(r)
    assert any("Add evidence" in x for x in recs)


# --------------------------------------------------------------------- explanation (no chain-of-thought)
def test_explanation_is_structured_metadata():
    r = ReasoningEngine().verify(answer_text="A mutex ensures mutual exclusion.",
                                 evidence=[_ev(1, "A mutex ensures mutual exclusion")], mode="fast")
    ex = StructuredExplanationGenerator().explain(r)
    assert set(ex.keys()) >= {"verification_path", "evidence_selection", "confidence", "contradictions", "citations"}
    assert "how" in ex["confidence"] and isinstance(ex["verification_path"], list)


# --------------------------------------------------------------------- engine: status + cache + normalize
def test_engine_status_verified_vs_failed():
    good = ReasoningEngine().verify(
        answer_text="A mutex provides mutual exclusion so a single thread enters the critical section [1].",
        evidence=[_ev(1, "A mutex provides mutual exclusion so a single thread enters the critical section")],
        mode="fast", signals={"success": True})
    assert good.status in (STATUS_VERIFIED, STATUS_WARNING) and good.confidence.overall > 0.5
    bad = ReasoningEngine().verify(answer_text="Teleportation is a common CPU scheduling algorithm.",
                                   evidence=[_ev(1, "Round robin is a CPU scheduling algorithm")], mode="fast")
    assert bad.status in (STATUS_WARNING, STATUS_FAILED)


def test_engine_cache_hits():
    eng = ReasoningEngine()
    a = eng.verify(answer_text="A cat is a mammal that purrs.", evidence=[_ev(1, "A cat is a mammal")], mode="fast")
    b = eng.verify(answer_text="A cat is a mammal that purrs.", evidence=[_ev(1, "A cat is a mammal")], mode="fast")
    assert a is b                                          # identical (answer, evidence, mode) → cached object


def test_to_evidence_refs_normalizes_and_reindexes():
    refs = to_evidence_refs([
        {"text": "first", "confidence": 0.9, "source_type": "transcript", "timespan": "0:10-0:20"},
        {"text": "", "score": 0.5},                        # empty → dropped
        EvidenceRef(index=99, text="third", score=0.3)])
    assert [r.index for r in refs] == [1, 2] and refs[0].modality == "audio"
