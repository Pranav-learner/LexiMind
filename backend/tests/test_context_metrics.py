"""Unit tests for context quality metrics."""

from app.context.metrics import citation_coverage, compute_metrics, context_density, context_relevance
from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter
from tests.test_context_helpers import mk


def _ev(chunk_id, text, **kw):
    return Evidence.from_chunk(mk(chunk_id, text, **kw))


def test_context_relevance_fraction_of_keywords_present():
    ev = [_ev("a", "scheduling of processes")]
    # 1 of 2 keywords ("scheduling" present, "memory" absent)
    assert context_relevance(ev, ["scheduling", "memory"]) == 0.5


def test_context_density_sentences_touching_query():
    text = "Scheduling matters. Totally unrelated filler."
    assert context_density(text, ["scheduling"]) == 0.5


def test_citation_coverage_complete_vs_incomplete():
    complete = _ev("a", "x", page_number=1)               # has source+doc+page
    incomplete = _ev("b", "x", page_number=None)          # missing page
    assert citation_coverage([complete]) == 1.0
    assert citation_coverage([complete, incomplete]) == 0.5


def test_compute_metrics_token_efficiency_and_compression():
    ev = [_ev("a", "scheduling processes")]
    m = compute_metrics(
        evidence=ev, context_text="[1] d.pdf · Page 1\nscheduling processes",
        query_keywords=["scheduling"], raw_tokens=100, final_tokens=40,
        num_input_chunks=4, num_duplicates_removed=1, counter=TokenCounter(),
    )
    assert m["token_efficiency"] == 0.4
    assert m["compression_ratio"] == 0.6
    assert m["duplicate_reduction_rate"] == 0.25
    assert m["num_chunks_used"] == 1
