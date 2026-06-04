"""Unit tests for metadata filtering."""

from app.retrieval.filters import build_filter
from app.retrieval.schemas import RetrievalFilter, RetrievedChunk


def _chunk(cid, **meta):
    meta["chunk_id"] = cid
    return RetrievedChunk(chunk_id=cid, text=cid, metadata=meta)


def test_empty_filter_matches_everything():
    f = RetrievalFilter()
    assert f.is_empty()
    chunks = [_chunk("a", source="x"), _chunk("b", source="y")]
    assert f.apply(chunks) == chunks


def test_single_value_filter():
    f = RetrievalFilter(source="x.pdf")
    chunks = [_chunk("a", source="x.pdf"), _chunk("b", source="y.pdf")]
    assert [c.chunk_id for c in f.apply(chunks)] == ["a"]


def test_list_value_is_or_within_field():
    f = RetrievalFilter(topic=["os", "java"])
    chunks = [_chunk("a", topic="os"), _chunk("b", topic="pets"), _chunk("c", topic="java")]
    assert {c.chunk_id for c in f.apply(chunks)} == {"a", "c"}


def test_multiple_fields_are_anded():
    f = RetrievalFilter(source="x.pdf", topic="os")
    chunks = [
        _chunk("a", source="x.pdf", topic="os"),
        _chunk("b", source="x.pdf", topic="pets"),
        _chunk("c", source="y.pdf", topic="os"),
    ]
    assert [c.chunk_id for c in f.apply(chunks)] == ["a"]


def test_build_filter_drops_empty_and_unknown():
    assert build_filter(None) is None
    assert build_filter({}) is None
    assert build_filter({"source": "  "}) is None
    assert build_filter({"unknown": "v"}) is None
    f = build_filter({"document_id": "doc_1", "source": ["a.pdf", " "], "junk": 1})
    assert f.document_id == "doc_1"
    assert f.source == ["a.pdf"]
