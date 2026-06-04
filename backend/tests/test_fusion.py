"""Unit tests for Reciprocal Rank Fusion."""

import pytest

from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.schemas import RetrievedChunk


def _chunk(cid, retriever="x"):
    return RetrievedChunk(chunk_id=cid, text=cid, metadata={"chunk_id": cid}, retriever=retriever)


def test_rrf_orders_by_summed_reciprocal_rank():
    dense = [_chunk("a", "dense"), _chunk("b", "dense"), _chunk("c", "dense")]
    sparse = [_chunk("b", "bm25"), _chunk("a", "bm25"), _chunk("d", "bm25")]

    fused = reciprocal_rank_fusion([dense, sparse], k=60)
    ids = [c.chunk_id for c in fused]

    # a: 1/61 + 1/62 ; b: 1/62 + 1/61  -> tie, both above c and d.
    assert set(ids[:2]) == {"a", "b"}
    assert set(ids[2:]) == {"c", "d"}
    # ranks are 1-based and contiguous
    assert [c.rank for c in fused] == [1, 2, 3, 4]


def test_rrf_dedups_by_chunk_id_and_records_contributors():
    dense = [_chunk("a", "dense")]
    sparse = [_chunk("a", "bm25")]
    fused = reciprocal_rank_fusion([dense, sparse], k=10)
    assert len(fused) == 1
    assert fused[0].chunk_id == "a"
    assert pytest.approx(fused[0].score) == (1 / 11) + (1 / 11)
    assert "dense" in fused[0].retriever and "bm25" in fused[0].retriever


def test_rrf_weights_break_ties():
    dense = [_chunk("a", "dense")]
    sparse = [_chunk("b", "bm25")]
    fused = reciprocal_rank_fusion([dense, sparse], k=60, weights=[2.0, 1.0])
    assert fused[0].chunk_id == "a"  # dense weighted higher


def test_rrf_top_k_truncates():
    lst = [_chunk(c) for c in "abcdef"]
    fused = reciprocal_rank_fusion([lst], k=60, top_k=3)
    assert len(fused) == 3


def test_rrf_rejects_nonpositive_k():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[_chunk("a")]], k=0)


def test_rrf_rejects_mismatched_weights():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[_chunk("a")], [_chunk("b")]], weights=[1.0])
