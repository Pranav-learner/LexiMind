"""Integration tests for the full context engine (ContextBuilderService).

No models/LLM involved — a word-count token counter makes budgeting deterministic.
"""

from app.context.builder import ContextBuilderService
from app.context.tokenizer import TokenCounter
from tests.test_context_helpers import mk


def _builder(window):
    return ContextBuilderService(
        counter=TokenCounter(lambda t: len(t.split())),
        context_window=window,
        system_reserve=0,
        response_reserve=0,
        enable_compression=True,
    )


def test_dedup_budget_and_citations_end_to_end():
    chunks = [
        mk("a", "alpha one two three four", score=0.9, document_id="doc_a", source="A.pdf", page_number=1),
        mk("b", "alpha one two three four", score=0.2, document_id="doc_a", source="A.pdf", page_number=1),  # dup of a
        mk("c", "beta five six seven eight", score=0.7, document_id="doc_b", source="B.pdf", page_number=2),
        mk("d", "gamma nine ten eleven twelve thirteen", score=0.1, document_id="doc_c", source="C.pdf", page_number=3),
    ]
    ctx = _builder(window=14).build("what", chunks)  # available = 14 - 1 (user) = 13 tokens

    assert ctx.metrics["num_duplicates_removed"] == 1            # b removed
    assert ctx.metrics["citation_coverage"] == 1.0              # all citations complete
    assert ctx.metrics["final_tokens"] <= ctx.metrics["available_context_budget"]
    assert ctx.context.startswith("[1]")                        # numbered, assembled
    assert ctx.num_chunks_used >= 1
    # No kept evidence ever loses its citation.
    assert all(e.citations for e in ctx.evidence)


def test_merge_preserves_all_citations():
    chunks = [
        mk("m1", "First sentence here.", score=0.5, document_id="doc_x", source="X.pdf", page_number=1, start_paragraph=0, end_paragraph=0),
        mk("m2", "Second sentence here.", score=0.5, document_id="doc_x", source="X.pdf", page_number=1, start_paragraph=1, end_paragraph=1),
    ]
    ctx = _builder(window=1000).build("anything", chunks)
    all_citation_ids = {c.chunk_id for e in ctx.evidence for c in e.citations}
    assert {"m1", "m2"} <= all_citation_ids                     # merged, nothing lost


def test_empty_chunks_yield_empty_context_with_metrics():
    ctx = _builder(window=100).build("q", [])
    assert ctx.context == ""
    assert ctx.num_chunks_used == 0
    assert "citation_coverage" in ctx.metrics


def test_budget_prevents_overflow_with_many_chunks():
    chunks = [mk(f"c{i}", "word " * 10, score=1.0 - i * 0.01, document_id=f"doc_{i}", page_number=i + 1)
              for i in range(20)]
    ctx = _builder(window=30).build("q", chunks)  # available 29 tokens, each chunk ~10
    assert ctx.metrics["final_tokens"] <= 29
    assert ctx.num_chunks_used < 20                            # most dropped by budget
