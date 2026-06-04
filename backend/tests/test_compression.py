"""Unit tests for ContextCompressor (merge, redundancy removal, extractive fit)."""

from app.context.compression import ContextCompressor, ExtractiveStrategy
from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter
from tests.test_context_helpers import mk


def _ev(chunk_id, text, *, score=0.5, **kw):
    e = Evidence.from_chunk(mk(chunk_id, text, score=score, **kw))
    e.evidence_score = score
    return e


def _compressor():
    return ContextCompressor(TokenCounter(lambda t: len(t.split())))


def test_merge_overlapping_unions_citations():
    a = _ev("a", "First part about scheduling.", document_id="doc_os", page_number=5)
    b = _ev("b", "Second part about scheduling.", document_id="doc_os", page_number=5)
    merged = _compressor().merge_overlapping([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert {c.chunk_id for c in m.citations} == {"a", "b"}   # no citation lost
    assert "b" in m.merged_from
    assert "First part" in m.text and "Second part" in m.text


def test_merge_keeps_different_documents_separate():
    a = _ev("a", "alpha", document_id="doc_a", page_number=1)
    b = _ev("b", "beta", document_id="doc_b", page_number=1)
    assert len(_compressor().merge_overlapping([a, b])) == 2


def test_remove_redundancy_drops_repeated_sentences():
    a = _ev("a", "Shared sentence here. Unique to A.", score=0.9)
    b = _ev("b", "Shared sentence here. Unique to B.", score=0.4)
    out = _compressor().remove_redundancy([a, b])
    # A keeps both; B loses the shared sentence but keeps its unique one + its citation.
    assert "Unique to A" in out[0].text
    assert "Shared sentence here" not in out[1].text
    assert "Unique to B" in out[1].text
    assert out[1].citations[0].chunk_id == "b"


def test_compress_to_fit_reduces_tokens_and_preserves_citation():
    long = "Irrelevant filler one. The prerequisites are math and python. Irrelevant filler two. More filler three."
    ev = _ev("a", long)
    comp = _compressor()
    before = comp.counter.count(ev.text)
    out = comp.compress_to_fit(ev, target_tokens=6, query_keywords=["prerequisites", "math", "python"])
    assert comp.counter.count(out.text) <= before
    assert out.compressed is True
    assert "prerequisites" in out.text.lower()
    assert out.citations[0].chunk_id == "a"   # citation preserved through compression


def test_extractive_strategy_single_sentence_noop():
    s = ExtractiveStrategy()
    assert s.summarize("only one sentence", 1, ["one"], TokenCounter(lambda t: len(t.split())))
