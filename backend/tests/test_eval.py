"""Unit tests for the retrieval evaluation framework."""

from app.eval.framework import EvalQuery, RetrievalEvaluator
from app.retrieval.schemas import RetrievedChunk


def _chunk(cid):
    return RetrievedChunk(chunk_id=cid, text=cid, metadata={"chunk_id": cid})


def test_perfect_retrieval_scores_one():
    dataset = [EvalQuery(query="q", relevant_chunk_ids=["a"])]
    ev = RetrievalEvaluator(dataset, k_values=[1, 3])

    report = ev.evaluate(lambda q: [_chunk("a"), _chunk("b"), _chunk("c")])
    assert report.recall_at_k[1] == 1.0
    assert report.precision_at_k[1] == 1.0
    assert report.mrr == 1.0


def test_relevant_at_rank_two_gives_half_mrr():
    dataset = [EvalQuery(query="q", relevant_chunk_ids=["b"])]
    ev = RetrievalEvaluator(dataset, k_values=[1, 3])
    report = ev.evaluate(lambda q: [_chunk("a"), _chunk("b"), _chunk("c")])
    assert report.mrr == 0.5
    assert report.recall_at_k[1] == 0.0
    assert report.recall_at_k[3] == 1.0
    assert report.precision_at_k[3] == 1 / 3


def test_recall_with_multiple_relevant():
    dataset = [EvalQuery(query="q", relevant_chunk_ids=["a", "c", "z"])]
    ev = RetrievalEvaluator(dataset, k_values=[3])
    report = ev.evaluate(lambda q: [_chunk("a"), _chunk("b"), _chunk("c")])
    # 2 of 3 relevant retrieved in top-3
    assert report.recall_at_k[3] == 2 / 3
    assert report.precision_at_k[3] == 2 / 3


def test_source_level_ground_truth():
    dataset = [EvalQuery(query="q", relevant_sources=["os.pdf"])]
    ev = RetrievalEvaluator(dataset, k_values=[1])
    c = RetrievedChunk(chunk_id="x", text="x", metadata={"chunk_id": "x", "source": "os.pdf"})
    report = ev.evaluate(lambda q: [c])
    assert report.recall_at_k[1] == 1.0


def test_report_markdown_renders():
    dataset = [EvalQuery(query="q", relevant_chunk_ids=["a"])]
    ev = RetrievalEvaluator(dataset, k_values=[1])
    md = ev.evaluate(lambda q: [_chunk("a")]).to_markdown()
    assert "Recall@K" in md and "MRR" in md
