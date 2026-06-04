"""LexiMind retrieval layer.

Pipeline (Phase 1):

    Query
      -> Query Analysis        (query_analysis.py)
      -> Dense Retrieval       (dense_retriever.py)
      -> Sparse Retrieval BM25 (bm25_retriever.py)
      -> Hybrid Fusion (RRF)   (hybrid_retriever.py + fusion.py)
      -> Metadata Filtering    (filters.py)
      -> Reranking             (reranker.py)
      -> Context Builder       (pipeline.py)
      -> LLM

The orchestrator that wires these together is `RetrievalPipeline` in pipeline.py.
"""

from app.retrieval.schemas import RetrievedChunk, RetrievalFilter

__all__ = ["RetrievedChunk", "RetrievalFilter"]
