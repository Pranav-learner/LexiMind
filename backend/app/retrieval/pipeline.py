"""RetrievalPipeline — the Phase-1 orchestrator.

    Query
      -> analyze_query            (query shape -> fusion weights)
      -> HybridRetriever          (dense + BM25 -> RRF)   [over-fetch: rerank_candidates]
      -> metadata filtering       (applied inside retrievers)
      -> RerankerService          (cross-encoder -> precise top_k)
      -> build_context            (numbered, deduped context block for the LLM)

This is the single place the whole retrieval flow is composed, so the API route and
(future) agents depend on one stable entry point: `RetrievalPipeline.run(query, ...)`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.query_analysis import QueryAnalysis, analyze_query
from app.retrieval.reranker import RerankerService
from app.retrieval.schemas import RetrievalFilter, RetrievedChunk


@dataclass
class RetrievalResult:
    query: str
    analysis: QueryAnalysis
    chunks: List[RetrievedChunk]
    context: str
    timings_ms: dict = field(default_factory=dict)


def build_context(chunks: List[RetrievedChunk], *, max_chars: Optional[int] = None) -> str:
    """Assemble a numbered context block from final chunks.

    Each chunk is labeled [n] with its page so the LLM (and citations) can reference it.
    `max_chars` provides a simple token-budget guard; later phases replace this with a
    real token budgeter / compressor.
    """
    parts: List[str] = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        page = c.page_number
        header = f"[{i}] (Page {page})" if page is not None else f"[{i}]"
        block = f"{header}: {c.text}"
        if max_chars is not None and used + len(block) > max_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


class RetrievalPipeline:
    def __init__(
        self,
        hybrid: HybridRetriever,
        reranker: Optional[RerankerService] = None,
        *,
        rerank_candidates: int = 30,
        final_top_k: int = 5,
        dense_top_k: int = 30,
        sparse_top_k: int = 30,
        enable_reranker: bool = True,
    ):
        self.hybrid = hybrid
        self.reranker = reranker
        self.rerank_candidates = rerank_candidates
        self.final_top_k = final_top_k
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k
        self.enable_reranker = enable_reranker

    def run(
        self,
        query: str,
        *,
        embed_fn: Callable[[str], List[float]],
        filters: Optional[RetrievalFilter] = None,
        final_top_k: Optional[int] = None,
        context_max_chars: Optional[int] = None,
    ) -> RetrievalResult:
        timings: dict = {}
        final_top_k = final_top_k or self.final_top_k

        t0 = time.perf_counter()
        analysis = analyze_query(query)
        timings["analysis_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        query_embedding = embed_fn(analysis.normalized or query)
        timings["embed_ms"] = (time.perf_counter() - t0) * 1000

        dense_w, sparse_w = analysis.dense_sparse_weights()
        self.hybrid.dense_weight = dense_w
        self.hybrid.sparse_weight = sparse_w

        t0 = time.perf_counter()
        candidates = self.hybrid.retrieve(
            query=analysis.normalized or query,
            query_embedding=query_embedding,
            dense_top_k=self.dense_top_k,
            sparse_top_k=self.sparse_top_k,
            top_k=self.rerank_candidates,
            filters=filters,
        )
        timings["retrieval_ms"] = (time.perf_counter() - t0) * 1000

        if self.enable_reranker and self.reranker is not None and candidates:
            t0 = time.perf_counter()
            final_chunks = self.reranker.rerank(query, candidates, top_k=final_top_k)
            timings["rerank_ms"] = (time.perf_counter() - t0) * 1000
        else:
            final_chunks = candidates[:final_top_k]
            timings["rerank_ms"] = 0.0

        context = build_context(final_chunks, max_chars=context_max_chars)
        timings["total_ms"] = sum(
            timings.get(k, 0.0) for k in ("analysis_ms", "embed_ms", "retrieval_ms", "rerank_ms")
        )

        return RetrievalResult(
            query=query,
            analysis=analysis,
            chunks=final_chunks,
            context=context,
            timings_ms=timings,
        )
