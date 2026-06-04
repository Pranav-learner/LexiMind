"""Lightweight query analysis run *before* retrieval.

WHY (and why lightweight):
- Different queries want different retrieval behavior. A keyword-y query ("BM25 okapi
  parameter k") should lean on sparse retrieval; a natural-language question ("how does
  the OS schedule processes?") leans dense. Knowing the query shape lets the pipeline
  weight fusion and pick depths intelligently — and gives downstream agents structured
  signals.
- This is deliberately rule-based (no LLM call) to stay fast and offline. It is the
  seam where future capabilities plug in: extracted filters, metadata constraints,
  multimodal routing. The dataclass already carries `suggested_filters` and
  `wants_modalities` placeholders so those can be populated later without changing the
  pipeline's call site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.retrieval.bm25_retriever import tokenize
from app.retrieval.schemas import RetrievalFilter

_QUESTION_WORDS = {"what", "why", "how", "when", "where", "who", "which", "whom", "whose"}
_DEFINITION_HINTS = {"define", "definition", "meaning", "what is", "what are"}
_COMPARE_HINTS = {"compare", "difference", "versus", "vs", "differ"}
_SUMMARY_HINTS = {"summarize", "summary", "overview", "tl;dr", "outline"}


@dataclass
class QueryAnalysis:
    raw: str
    normalized: str
    query_type: str          # "question" | "keyword" | "definition" | "comparison" | "summary"
    intent: str              # short human-readable intent label
    keywords: List[str]      # content tokens (stopwords removed)
    is_keyword_heavy: bool   # few/no function words -> favor sparse retrieval
    # Forward-looking seams (populated by later phases; empty for now):
    suggested_filters: Optional[RetrievalFilter] = None
    wants_modalities: List[str] = field(default_factory=lambda: ["text"])

    def dense_sparse_weights(self) -> tuple[float, float]:
        """Fusion weights (dense, sparse) implied by the query shape.

        Keyword-heavy / definition / exact-ish queries trust BM25 more; natural-language
        questions trust dense more. Weights are intentionally mild so neither retriever
        is silenced — RRF still sees both lists.
        """
        if self.query_type in ("definition", "keyword") or self.is_keyword_heavy:
            return (1.0, 1.3)
        if self.query_type in ("question", "summary"):
            return (1.3, 1.0)
        return (1.0, 1.0)


def analyze_query(query: str) -> QueryAnalysis:
    raw = query or ""
    normalized = re.sub(r"\s+", " ", raw.strip())
    lower = normalized.lower()
    keywords = tokenize(normalized)

    # Classify (first match wins; order matters).
    if any(h in lower for h in _SUMMARY_HINTS):
        query_type, intent = "summary", "summarize content"
    elif any(h in lower for h in _COMPARE_HINTS):
        query_type, intent = "comparison", "compare entities"
    elif any(h in lower for h in _DEFINITION_HINTS):
        query_type, intent = "definition", "define a term"
    elif lower.endswith("?") or any(lower.startswith(w + " ") for w in _QUESTION_WORDS):
        query_type, intent = "question", "answer a question"
    else:
        query_type, intent = "keyword", "lexical lookup"

    # "Keyword-heavy" = most surviving tokens are content words (few stopwords present),
    # which is the signal that exact lexical matching (BM25) will pay off.
    total_words = len(_TOKENS(normalized))
    is_keyword_heavy = total_words > 0 and (len(keywords) / total_words) >= 0.8

    return QueryAnalysis(
        raw=raw,
        normalized=normalized,
        query_type=query_type,
        intent=intent,
        keywords=keywords,
        is_keyword_heavy=is_keyword_heavy,
    )


_WORD_RE = re.compile(r"[a-z0-9]+")


def _TOKENS(text: str) -> List[str]:
    """All word tokens (stopwords included) — used to measure keyword density."""
    return _WORD_RE.findall(text.lower())
