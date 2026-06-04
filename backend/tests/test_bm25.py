"""Unit tests for BM25Retriever (sparse retrieval)."""

from app.retrieval.bm25_retriever import BM25Retriever, tokenize
from app.retrieval.schemas import RetrievalFilter


class FakeStore:
    """Minimal stand-in: BM25Retriever only reads `.metadata`."""

    def __init__(self, records):
        self.metadata = records


def _records():
    return [
        {"chunk_id": "c0", "text": "the cat sat on the mat", "source": "a.pdf", "topic": "pets"},
        {"chunk_id": "c1", "text": "operating systems schedule processes and threads", "source": "os.pdf", "topic": "os"},
        {"chunk_id": "c2", "text": "java generics and collections framework", "source": "java.pdf", "topic": "java"},
        {"chunk_id": "c3", "text": "the dog chased the cat around the yard", "source": "a.pdf", "topic": "pets"},
    ]


def test_tokenize_removes_stopwords_keeps_numbers():
    assert tokenize("The BM25 k1 parameter is 1.2") == ["bm25", "k1", "parameter", "1", "2"]


def test_bm25_ranks_lexical_match_first():
    store = FakeStore(_records())
    bm25 = BM25Retriever(store)
    results = bm25.retrieve("process scheduling in operating systems", top_k=2)
    assert results[0].chunk_id == "c1"
    assert results[0].rank == 1


def test_bm25_empty_corpus_returns_empty():
    bm25 = BM25Retriever(FakeStore([]))
    assert bm25.retrieve("anything", top_k=5) == []


def test_bm25_rebuilds_when_corpus_grows():
    store = FakeStore(_records())
    bm25 = BM25Retriever(store)
    bm25.retrieve("cat", top_k=1)  # builds index for 4 docs

    store.metadata.append(
        {"chunk_id": "c4", "text": "feline cat behavior and pet care", "source": "b.pdf", "topic": "pets"}
    )
    bm25.add_documents(1)  # marks dirty
    results = bm25.retrieve("pet care for a cat", top_k=5)
    ids = {r.chunk_id for r in results}
    assert "c4" in ids  # new doc is searchable after rebuild


def test_bm25_respects_metadata_filter():
    store = FakeStore(_records())
    bm25 = BM25Retriever(store)
    results = bm25.retrieve("cat", top_k=5, filters=RetrievalFilter(topic="pets"))
    assert all(r.metadata["topic"] == "pets" for r in results)
    assert {r.chunk_id for r in results} <= {"c0", "c3"}
