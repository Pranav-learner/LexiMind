"""Self Review Engine (Step 7) — review the draft and recommend improvements.

Two depths, BOTH bounded (no infinite loops — a single pass each):
- fast     — deterministic review from the verification report: flags unsupported/weak claims, broken/
             missing citations, contradictions, thin evidence, and turns them into concrete
             recommendations. No LLM.
- thorough — additionally makes ONE pass through the SINGLE answer pathway (`answer_fn`) asking the
             model to critique the draft against the evidence, and records its response as a review
             note. It never re-orchestrates generation and never loops — the model's note is advisory
             metadata, not a new answer.

Depth is configurable; the engine caps the LLM at one call so cost + latency stay bounded.
"""

from __future__ import annotations

from typing import List, Optional

from app.reasoning.interfaces import (
    CONFLICTING, SUPPORTED, UNSUPPORTED, WEAK, VerificationReport,
)

_REVIEW_SYSTEM = (
    "You are LexiMind's verification reviewer. Critique the draft answer STRICTLY against the numbered "
    "evidence. List (a) any statement not supported by the evidence, (b) any claim that contradicts the "
    "evidence, and (c) missing but important points. Be terse and specific. Do NOT rewrite the answer "
    "and do NOT reveal step-by-step reasoning — output only a short bulleted list of issues."
)


class SelfReviewEngine:
    name = "self-review-v1"

    def review(self, report: VerificationReport, *, answer_text: str, answer_fn=None,
               depth: str = "fast") -> List[str]:
        notes: List[str] = []
        counts = report.counts
        unsupported = counts.get(UNSUPPORTED, 0)
        conflicting = counts.get(CONFLICTING, 0)
        weak = counts.get(WEAK, 0)

        if unsupported:
            notes.append(f"{unsupported} claim(s) are unsupported by the evidence — add evidence or soften them.")
        if conflicting:
            notes.append(f"{conflicting} claim(s) conflict with the evidence — reconcile or flag them.")
        if weak:
            notes.append(f"{weak} claim(s) have only weak support — strengthen with better citations.")
        broken = [i for i in report.citation_issues if i.issue_type == "broken"]
        missing = [i for i in report.citation_issues if i.issue_type == "missing"]
        if broken:
            notes.append(f"{len(broken)} broken citation(s) reference non-existent evidence.")
        if missing:
            notes.append(f"{len(missing)} evidence-backed claim(s) are missing [n] citations.")
        if report.contradictions:
            notes.append(f"{len(report.contradictions)} contradiction(s) detected among sources/claims.")
        if not report.evidence:
            notes.append("No evidence was gathered — the answer cannot be verified.")
        if not notes:
            notes.append("No verification issues found; the draft is well grounded.")

        # thorough: a SINGLE optional LLM critique through the one inference pathway
        if depth == "thorough" and answer_fn is not None:
            llm_note = self._llm_review(report, answer_text, answer_fn)
            if llm_note:
                notes.append(f"Model review: {llm_note}")
        return notes

    @staticmethod
    def _llm_review(report: VerificationReport, answer_text: str, answer_fn) -> Optional[str]:
        ev = "\n".join(f"[{e.index}] {e.text}" for e in report.evidence[:20]) or "(no evidence)"
        prompt = (f"{_REVIEW_SYSTEM}\n\nEvidence:\n{ev}\n\nDraft answer:\n{answer_text[:4000]}\n\nIssues:\n")
        try:
            out = (answer_fn(prompt) or "").strip()
        except Exception:
            return None
        return out[:1200] or None


def recommendations_from(report: VerificationReport) -> List[str]:
    """Turn the report into a short, prioritized recommendation list (deterministic)."""
    recs: List[str] = []
    if report.status == "failed":
        recs.append("Do not rely on this answer without revision — verification failed.")
    for issue in report.citation_issues:
        if issue.issue_type == "broken":
            recs.append(f"Fix broken citation [{issue.citation_index}] on claim {issue.claim_id}.")
    for v in report.claim_verdicts:
        if v.status == CONFLICTING:
            recs.append(f"Resolve the conflict in: “{v.claim.text[:80]}”.")
        elif v.status == UNSUPPORTED:
            recs.append(f"Add evidence for: “{v.claim.text[:80]}”.")
    if report.confidence.overall < 0.5:
        recs.append("Gather more/stronger evidence to raise confidence before presenting this.")
    # dedupe preserving order, cap length
    seen, out = set(), []
    for r in recs:
        if r not in seen:
            seen.add(r); out.append(r)
    return out[:8]
