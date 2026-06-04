"""Unit tests for HybridRetriever (dense + BM25 fused via RRF)."""

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.schemas import RetrievedChunk


class FakeStore:
    def __init__(self, records):
        self.metadata = records


class FakeDense:
    """Returns a fixed ranked list; ignores the embedding."""

    def __init__(self, ranked):
        self.ranked = ranked

    def retrieve(self, query_embedding, top_k, filters=None):
        out = list(self.ranked[:top_k])
        for rank, c in enumerate(out, start=1):
            c.rank = rank
        return out


def _records():
    return [
        {"chunk_id": "c0", "text": "operating systems schedule processes", "source": "os.pdf"},
        {"chunk_id": "c1", "text": "java collections and generics", "source": "java.pdf"},
        {"chunk_id": "c2", "text": "the cat sat on the mat", "source": "a.pdf"},
    ]


def test_hybrid_merges_both_retrievers():
    store = FakeStore(_records())
    bm25 = BM25Retriever(store)
    # Dense ranks c2 first; sparse (bm25) will rank c0 first for an OS query.
    dense = FakeDense([
        RetrievedChunk(chunk_id="c2", text="x", metadata={"chunk_id": "c2"}, retriever="dense"),
        RetrievedChunk(chunk_id="c0", text="x", metadata={"chunk_id": "c0"}, retriever="dense"),
    ])
    hybrid = HybridRetriever(dense, bm25, rrf_k=60)

    fused = hybrid.retrieve(
        query="process scheduling in operating systems",
        query_embedding=[0.0],
        dense_top_k=5,
        sparse_top_k=5,
        top_k=5,
    )
    ids = {c.chunk_id for c in fused}
    assert "c0" in ids and "c2" in ids       # contributions from both retrievers
    assert all(c.retriever.startswith("rrf") for c in fused)


def test_hybrid_dedups_shared_candidate_to_top():
    store = FakeStore(_records())
    bm25 = BM25Retriever(store)
    dense = FakeDense([
        RetrievedChunk(chunk_id="c0", text="x", metadata={"chunk_id": "c0"}, retriever="dense"),
    ])
    hybrid = HybridRetriever(dense, bm25, rrf_k=60)
    fused = hybrid.retrieve(
        query="operating systems schedule processes",
        query_embedding=[0.0],
        dense_top_k=5,
        sparse_top_k=5,
        top_k=5,
    )
    # c0 appears in BOTH lists -> highest fused score -> rank 1, no duplicate entry.
    assert fused[0].chunk_id == "c0"
    assert [c.chunk_id for c in fused].count("c0") == 1
