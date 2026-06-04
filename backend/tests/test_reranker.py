"""Unit tests for RerankerService (with a fake cross-encoder, no model download)."""

from app.retrieval.reranker import RerankerService
from app.retrieval.schemas import RetrievedChunk


class FakeCrossEncoder:
    """Scores a pair by a lookup table; counts predict() calls for cache assertions."""

    def __init__(self, table):
        self.table = table
        self.calls = 0
        self.pairs_seen = []

    def predict(self, pairs, batch_size=32):
        self.calls += 1
        self.pairs_seen.extend(pairs)
        return [self.table[text] for (_q, text) in pairs]


def _candidates():
    return [
        RetrievedChunk(chunk_id="a", text="low", metadata={"chunk_id": "a"}),
        RetrievedChunk(chunk_id="b", text="high", metadata={"chunk_id": "b"}),
        RetrievedChunk(chunk_id="c", text="mid", metadata={"chunk_id": "c"}),
    ]


def _service():
    svc = RerankerService(model_name="fake")
    svc._model = FakeCrossEncoder({"low": 0.1, "high": 0.9, "mid": 0.5})
    return svc


def test_rerank_sorts_by_cross_encoder_score():
    svc = _service()
    out = svc.rerank("q", _candidates())
    assert [c.chunk_id for c in out] == ["b", "c", "a"]
    assert [c.rank for c in out] == [1, 2, 3]
    assert out[0].retriever == "reranker"


def test_rerank_top_k():
    svc = _service()
    out = svc.rerank("q", _candidates(), top_k=2)
    assert [c.chunk_id for c in out] == ["b", "c"]


def test_rerank_batches_all_misses_in_one_call():
    svc = _service()
    svc.rerank("q", _candidates())
    assert svc._model.calls == 1  # all three pairs scored in a single predict()


def test_rerank_uses_cache_on_repeat():
    svc = _service()
    svc.rerank("q", _candidates())
    svc.rerank("q", _candidates())  # identical (query, chunk_id) pairs -> all cache hits
    assert svc._model.calls == 1


def test_rerank_empty_is_noop():
    svc = _service()
    assert svc.rerank("q", []) == []
    assert svc._model.calls == 0
