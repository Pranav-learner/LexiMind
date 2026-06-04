"""Context quality metrics (Phase 2, Task 8 + Step 5).

Pure functions over evidence + the assembled context, so they're trivially testable and
reusable by both the live pipeline (attached to every ContextResult) and the eval suite.

Metrics:
  - context_relevance    : how on-topic the kept evidence is (mean query-keyword coverage)
  - context_density      : signal-to-noise — fraction of context sentences touching the query
  - citation_coverage    : fraction of evidence carrying a COMPLETE citation
  - token_efficiency     : final context tokens / raw retrieved tokens (lower = leaner)
  - compression_ratio    : 1 - token_efficiency (higher = more saved)
  - duplicate_reduction  : fraction of input chunks removed as duplicates
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence

from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def context_relevance(evidence: List[Evidence], query_keywords: Sequence[str]) -> float:
    if not evidence or not query_keywords:
        return 0.0
    kw = set(query_keywords)
    total = 0.0
    for ev in evidence:
        tokens = set(_WORD_RE.findall(ev.text.lower()))
        total += len(kw & tokens) / len(kw)
    return total / len(evidence)


def context_density(context_text: str, query_keywords: Sequence[str]) -> float:
    if not context_text or not query_keywords:
        return 0.0
    kw = set(query_keywords)
    sentences = [s for s in _SENTENCE_RE.split(context_text) if s.strip()]
    if not sentences:
        return 0.0
    hits = sum(1 for s in sentences if kw & set(_WORD_RE.findall(s.lower())))
    return hits / len(sentences)


def citation_coverage(evidence: List[Evidence]) -> float:
    if not evidence:
        return 0.0
    complete = sum(1 for ev in evidence if ev.citations and all(c.is_complete() for c in ev.citations))
    return complete / len(evidence)


def compute_metrics(
    *,
    evidence: List[Evidence],
    context_text: str,
    query_keywords: Sequence[str],
    raw_tokens: int,
    final_tokens: int,
    num_input_chunks: int,
    num_duplicates_removed: int,
    counter: TokenCounter,
) -> Dict[str, float]:
    token_efficiency = (final_tokens / raw_tokens) if raw_tokens else 0.0
    return {
        "context_relevance": round(context_relevance(evidence, query_keywords), 4),
        "context_density": round(context_density(context_text, query_keywords), 4),
        "citation_coverage": round(citation_coverage(evidence), 4),
        "token_efficiency": round(token_efficiency, 4),
        "compression_ratio": round(1.0 - token_efficiency, 4) if raw_tokens else 0.0,
        "duplicate_reduction_rate": round(num_duplicates_removed / num_input_chunks, 4) if num_input_chunks else 0.0,
        "raw_tokens": raw_tokens,
        "final_tokens": final_tokens,
        "num_input_chunks": num_input_chunks,
        "num_chunks_used": len(evidence),
        "num_duplicates_removed": num_duplicates_removed,
    }
