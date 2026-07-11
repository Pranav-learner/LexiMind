"""Cross-modal duplicate detection (Step 3) — extends Phase-2 text dedup to every modality.

Strategy (documented): cluster evidence by CONTENT token-set Jaccard ≥ threshold, regardless of
modality — so a text passage and the OCR of the same page (Text ↔ OCR), or a diagram and its caption
(Text ↔ Diagram Caption), collapse into one item. The representative is the highest-scored member;
the others are recorded as `merged_from` and their modalities unioned into `contributing_modalities`
(so the merge is traceable and the citation to every source is preserved). COMPLEMENTARY evidence —
different content that happens to be related — has low overlap and is NEVER removed. Pure + testable.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from app.mmcontext.schemas import MMEvidence

_WORD = re.compile(r"[a-z0-9]+")
DEFAULT_THRESHOLD = 0.82


def _tokens(text: str) -> set:
    return set(_WORD.findall((text or "").lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def deduplicate(evidence: List[MMEvidence], *, threshold: float = DEFAULT_THRESHOLD) -> Tuple[List[MMEvidence], int]:
    """Return (deduped, removed_count). Order-preserving by strongest representative."""
    kept: List[MMEvidence] = []
    token_cache: List[set] = []
    removed = 0

    # Process strongest first so the representative is the best-scored version.
    for ev in sorted(evidence, key=lambda e: e.base_score, reverse=True):
        etoks = _tokens(ev.content)
        merged = False
        for rep, rtoks in zip(kept, token_cache):
            if _jaccard(etoks, rtoks) >= threshold:
                # Duplicate → merge into the representative (keep richest content, union sources).
                rep.merged_from.append(ev.key)
                for m in ([ev.modality] + ev.contributing_modalities):
                    if m not in rep.contributing_modalities:
                        rep.contributing_modalities.append(m)
                if len(ev.content) > len(rep.content):
                    rep.content = ev.content
                merged = True
                removed += 1
                break
        if not merged:
            if ev.modality not in ev.contributing_modalities:
                ev.contributing_modalities.insert(0, ev.modality)
            kept.append(ev)
            token_cache.append(etoks)
    return kept, removed
