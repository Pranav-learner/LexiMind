"""Hybrid retrieval: dense + sparse, merged via Reciprocal Rank Fusion.

    Query embedding -> DenseRetriever  --\
                                          >-- RRF --> fused candidates
    Query text      -> BM25Retriever   --/

Responsibilities (kept narrow on purpose):
- Run both retrievers (each already applies metadata filters).
- Fuse with RRF (rank-based, scale-free).
- Deduplicate by chunk_id (handled inside RRF) while preserving metadata.

Reranking and context building live downstream in RetrievalPipeline, so this class
stays a pure "candidate generator" that is easy to test in isolation.
"""

from __future__ import annotations

from typing import List, Optional

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.dense_retriever import DenseRetriever
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.schemas import RetrievalFilter, RetrievedChunk


class HybridRetriever:
    def __init__(
        self,
        dense: DenseRetriever,
        sparse: BM25Retriever,
        *,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ):
        self.dense = dense
        self.sparse = sparse
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight

    def retrieve(
        self,
        query: str,
        query_embedding: List[float],
        *,
        dense_top_k: int = 30,
        sparse_top_k: int = 30,
        top_k: int = 30,
        filters: Optional[RetrievalFilter] = None,
    ) -> List[RetrievedChunk]:
        """Return up to `top_k` fused candidates, best-first.

        The caller computes `query_embedding` once and passes it in (it is reused
        nowhere else, but keeping embedding out of this class keeps it testable with
        a fake DenseRetriever).
        """
        dense_hits = self.dense.retrieve(query_embedding, dense_top_k, filters=filters)
        sparse_hits = self.sparse.retrieve(query, sparse_top_k, filters=filters)

        fused = reciprocal_rank_fusion(
            [dense_hits, sparse_hits],
            k=self.rrf_k,
            weights=[self.dense_weight, self.sparse_weight],
            top_k=top_k,
        )
        return fused
