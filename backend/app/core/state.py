"""Process-wide singletons for retrieval.

WHY this exists:
- Before Phase 1 the FAISS VectorStore was a module-level global *inside the upload
  route* (`app/api/upload.py`), and the query route imported it from there. That
  coupled HTTP routing to storage and made it impossible to construct the retrieval
  stack for tests or scripts without importing the web layer.
- This module owns the singletons (vector store + retrievers + pipeline) and is the one
  place they are built. Routes, scripts, and the eval harness all import from here.

The objects are created at import time. Models inside them load lazily: the embedding
model loads when embedding_service is first imported; the reranker model loads on the
first rerank call. So importing this module is cheap and offline-safe.
"""

from __future__ import annotations

from app.context.builder import ContextBuilderService
from app.core.config import settings
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.dense_retriever import DenseRetriever
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.reranker import RerankerService
from app.services.vector_store import VectorStore

# --- storage ---
vector_store = VectorStore(
    dimension=settings.embedding_dim,
    index_path=settings.index_path,
    metadata_path=settings.metadata_path,
)

# --- retrievers ---
dense_retriever = DenseRetriever(vector_store)
bm25_retriever = BM25Retriever(vector_store)
hybrid_retriever = HybridRetriever(dense_retriever, bm25_retriever, rrf_k=settings.rrf_k)

# --- reranker (model loads lazily on first use) ---
reranker = RerankerService(settings.reranker_model) if settings.enable_reranker else None

# --- pipeline ---
pipeline = RetrievalPipeline(
    hybrid_retriever,
    reranker,
    rerank_candidates=settings.rerank_candidates,
    final_top_k=settings.final_top_k,
    dense_top_k=settings.dense_top_k,
    sparse_top_k=settings.sparse_top_k,
    enable_reranker=settings.enable_reranker,
)

# --- context engine (Phase 2) ---
context_builder = ContextBuilderService(
    context_window=settings.context_window,
    system_reserve=settings.system_prompt_reserve,
    response_reserve=settings.response_reserve,
    dedup_threshold=settings.dedup_threshold,
    enable_compression=settings.enable_compression,
)
