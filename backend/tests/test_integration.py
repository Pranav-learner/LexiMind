"""End-to-end retrieval integration test.

Exercises the real pipeline (query analysis -> dense FAISS + BM25 -> RRF -> context)
with a tiny in-memory FAISS index and a deterministic fake embedding function. The
reranker is disabled here (covered separately in test_reranker with a fake model) so
the test needs no model download and runs in milliseconds.
"""

import os

import pytest

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.dense_retriever import DenseRetriever
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.schemas import RetrievalFilter
from app.services.vector_store import VectorStore


def fake_embed(text: str):
    """Deterministic 4-dim 'semantic' vector keyed on topic words."""
    t = text.lower()
    return [
        1.0 if any(w in t for w in ("process", "schedule", "os", "operating")) else 0.0,
        1.0 if any(w in t for w in ("java", "generic", "collection")) else 0.0,
        1.0 if any(w in t for w in ("cat", "dog", "pet")) else 0.0,
        0.1,
    ]


DOCS = [
    {"chunk_id": "os:0", "text": "operating systems schedule processes and threads", "source": "os.pdf", "page_number": 1, "topic": "os", "document_id": "doc_os"},
    {"chunk_id": "java:0", "text": "java generics and the collections framework", "source": "java.pdf", "page_number": 2, "topic": "java", "document_id": "doc_java"},
    {"chunk_id": "pet:0", "text": "the cat sat on the mat near the dog", "source": "pets.pdf", "page_number": 3, "topic": "pets", "document_id": "doc_pet"},
]


@pytest.fixture
def pipeline(tmp_path):
    store = VectorStore(
        dimension=4,
        index_path=os.path.join(tmp_path, "idx.faiss"),
        metadata_path=os.path.join(tmp_path, "meta.json"),
    )
    for doc in DOCS:
        store.add(fake_embed(doc["text"]), doc)

    hybrid = HybridRetriever(DenseRetriever(store), BM25Retriever(store), rrf_k=60)
    return RetrievalPipeline(
        hybrid,
        reranker=None,
        enable_reranker=False,
        rerank_candidates=10,
        final_top_k=3,
        dense_top_k=10,
        sparse_top_k=10,
    )


def test_end_to_end_retrieval(pipeline):
    result = pipeline.run("how does the OS schedule processes?", embed_fn=fake_embed)

    assert result.analysis.query_type == "question"
    assert result.chunks, "expected at least one retrieved chunk"
    assert result.chunks[0].chunk_id == "os:0"  # OS doc fused to the top
    assert "operating systems" in result.context
    assert "[1] (Page 1)" in result.context
    for key in ("analysis_ms", "embed_ms", "retrieval_ms", "total_ms"):
        assert key in result.timings_ms


def test_end_to_end_metadata_filter(pipeline):
    result = pipeline.run(
        "tell me about generics",
        embed_fn=fake_embed,
        filters=RetrievalFilter(source="java.pdf"),
    )
    assert result.chunks
    assert all(c.source == "java.pdf" for c in result.chunks)
