"""Duplicate / near-duplicate detection (Phase 2, Task 2).

WHY: retrieval (especially hybrid) often surfaces the same passage twice — once via dense,
once via BM25 — or two chunks that overlap heavily (adjacent paragraphs, a heading repeated
across pages). Sending duplicates to the LLM wastes tokens and skews its attention. We
remove them while keeping the HIGHEST-QUALITY version, so no information and no citation is
lost relative to keeping a worse duplicate.

Detection is lexical + metadata-aware (offline, deterministic):
  - exact: normalized text equality;
  - near : Jaccard similarity of word-token sets >= threshold;
  - structural: same document + same page + overlapping paragraph ranges.
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

from app.context.schemas import Evidence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _token_set(text: str) -> Set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _ranges_overlap(a_lo, a_hi, b_lo, b_hi) -> bool:
    if None in (a_lo, a_hi, b_lo, b_hi):
        return False
    return a_lo <= b_hi and b_lo <= a_hi


class DuplicateChunkDetector:
    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold

    def _is_structural_dup(self, a: Evidence, b: Evidence) -> bool:
        if not a.document_id or a.document_id != b.document_id:
            return False
        if a.page_number != b.page_number:
            return False
        return _ranges_overlap(
            a.start_paragraph, a.chunk.metadata.get("end_paragraph"),
            b.start_paragraph, b.chunk.metadata.get("end_paragraph"),
        )

    def detect(self, evidence: List[Evidence]) -> Tuple[List[Evidence], List[Evidence]]:
        """Return (kept, removed). Higher-quality evidence is preferred when duplicates clash."""
        # Process best-first so the survivor of any duplicate pair is the strongest one.
        ordered = sorted(
            evidence,
            key=lambda e: (e.evidence_score, e.retrieval_score, len(e.text)),
            reverse=True,
        )

        kept: List[Evidence] = []
        kept_tokens: List[Set[str]] = []
        removed: List[Evidence] = []

        for ev in ordered:
            tokens = _token_set(ev.text)
            is_dup = False
            for prev, prev_tokens in zip(kept, kept_tokens):
                if ev.text.strip() == prev.text.strip():
                    is_dup = True
                    break
                if _jaccard(tokens, prev_tokens) >= self.threshold:
                    is_dup = True
                    break
                if self._is_structural_dup(ev, prev):
                    is_dup = True
                    break
            if is_dup:
                removed.append(ev)
            else:
                kept.append(ev)
                kept_tokens.append(tokens)

        return kept, removed
