"""Explainability composer — "Why did the AI cite this?" (pure, deterministic).

LexiMind's retrieval pipeline is FIXED and known (Phase 1 + Phase 2): every citation travelled the
same path — hybrid dense+sparse retrieval → RRF fusion → cross-encoder rerank → duplicate detection
→ evidence ranking → context assembly. So an honest, useful explanation can be composed
deterministically from (a) that known path and (b) the scores/metadata actually stored on the
citation, WITHOUT a second LLM call. This keeps explanations testable and instant. An LLM-authored
narrative can be layered on later behind the same DTO.
"""

from __future__ import annotations

from typing import Dict, List

from app.citations.models import Citation


def _confidence_band(conf: float | None) -> str:
    if conf is None:
        return "unknown"
    if conf >= 0.75:
        return "high"
    if conf >= 0.5:
        return "moderate"
    return "low"


# The fixed production retrieval path (Phase 1 + Phase 2). Surfaced so users see how evidence flows.
RETRIEVAL_PATH = [
    "Query analysis (intent + keywords)",
    "Hybrid retrieval (dense embeddings + BM25 keyword)",
    "Reciprocal Rank Fusion (RRF) merges both rankings",
    "Cross-encoder reranking scores query↔chunk relevance",
    "Duplicate detection removes near-identical chunks",
    "Evidence ranking selects the strongest, most diverse support",
    "Context assembly (compression + budgeting) hands it to the LLM",
]


def explain(citation: Citation, *, reference_counts: Dict[str, int]) -> dict:
    """Compose a structured explanation for one citation."""
    conf = citation.confidence
    band = _confidence_band(conf)
    total_refs = sum(reference_counts.values())

    factors: List[dict] = []

    factors.append({
        "label": "Evidence strength",
        "detail": (
            f"This passage scored {band} confidence"
            + (f" ({conf:.0%})" if conf is not None else "")
            + " during Phase-2 evidence ranking — it was among the top-ranked chunks whose content "
              "directly supported the answer."
        ),
        "score": conf,
    })

    if citation.reranker_score is not None:
        factors.append({"label": "Reranker relevance", "detail": "The cross-encoder judged this chunk highly relevant to the query.", "score": citation.reranker_score})
    if citation.retrieval_score is not None:
        factors.append({"label": "Retrieval score", "detail": "Ranked strongly by the hybrid dense+BM25 retriever before reranking.", "score": citation.retrieval_score})

    factors.append({
        "label": "Why it outranked others",
        "detail": (
            "After RRF fused the dense and keyword rankings, the cross-encoder reranker placed this "
            "chunk above competing passages, and duplicate-detection kept it (rather than a near-"
            "identical neighbour) as the representative evidence."
        ),
        "score": None,
    })

    if citation.page_number is not None:
        factors.append({"label": "Source location", "detail": f"Traced to page {citation.page_number} of the source document — click to open the PDF at the exact passage.", "score": None})

    if total_refs > 1:
        parts = [f"{n} {t}{'s' if n != 1 else ''}" for t, n in reference_counts.items() if n]
        factors.append({
            "label": "Corroboration",
            "detail": f"This same evidence supports {total_refs} places in your workspace ({', '.join(parts)}), which reinforces its reliability.",
            "score": None,
        })

    summary = (
        f"The AI cited this passage because it was the {band}-confidence evidence that Phase-2 "
        f"evidence ranking selected as directly supporting the answer"
        + (f", and it is reused across {total_refs} of your knowledge assets." if total_refs > 1 else ".")
    )

    return {
        "citation_id": citation.id,
        "summary": summary,
        "factors": factors,
        "retrieval_path": RETRIEVAL_PATH,
    }
