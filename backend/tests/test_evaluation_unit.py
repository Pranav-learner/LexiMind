"""Unit tests for the Phase-8 Module-1 Evaluation framework — pure/offline (no HTTP, no LLM, no faiss).

Covers the metric engine, LLM judge parsing, regression detection + CI gate, pipeline comparison, dataset
validation, the eval cache, and the benchmark runner (with a fake pipeline + the reused retrieval report).
"""

from __future__ import annotations

from app.evaluation.cache import EvaluationCache
from app.evaluation.errors import InvalidDataset
from app.evaluation.datasets import validate_item
from app.evaluation.interfaces import EvalItemInput, PipelineOutput, RetrievedRef
from app.evaluation.judge import LLMJudge
from app.evaluation.metrics import MetricEngine
from app.evaluation.regression import PipelineComparator, RegressionDetector, compare_metrics
from app.evaluation.runner import BenchmarkRunner


# --------------------------------------------------------------------- metrics
def _item():
    return EvalItemInput(id="i1", question="what is a mutex?", expected_answer="A mutex gives mutual exclusion",
                         relevant_chunk_ids=["doc_x:1"], relevant_document_ids=["doc_x"])


def test_metric_engine_ranking_and_generation():
    out = PipelineOutput(
        retrieved=[RetrievedRef(chunk_id="doc_x:1", document_id="doc_x", score=0.9),
                   RetrievedRef(chunk_id="doc_y:3", document_id="doc_y", score=0.5)],
        answer="A mutex gives mutual exclusion to threads", citations=[{"document_id": "doc_x"}],
        verification={"confidence": {"overall": 0.8}, "counts": {"supported": 3, "unsupported": 1}})
    m = MetricEngine().compute(_item(), out)
    assert m["hit_rate"] == 1.0 and m["ndcg@1"] == 1.0
    assert m["citation_accuracy"] == 1.0 and m["ground_truth_match"] == 1.0
    assert m["verification_score"] == 0.8 and m["hallucination_rate"] == 0.25


def test_metric_skips_when_no_labels():
    out = PipelineOutput(retrieved=[RetrievedRef(chunk_id="a")], answer="x")
    m = MetricEngine().compute(EvalItemInput(id="i", question="q"), out)
    assert "hit_rate" not in m and "ground_truth_match" not in m   # nothing to score against


# --------------------------------------------------------------------- judge
def test_llm_judge_parses_scores():
    j = LLMJudge().judge(_item(), PipelineOutput(answer="an answer"),
                         answer_fn=lambda p: "quality: 4\ncompleteness: 5\nrelevance: 4\ncitation: 3\nreasonable")
    assert 0.7 <= j.overall <= 0.9 and j.scores["completeness"] == 1.0


def test_llm_judge_degrades_gracefully():
    j = LLMJudge().judge(_item(), PipelineOutput(answer="a"), answer_fn=lambda p: "garbage no scores")
    assert all(0.0 <= v <= 1.0 for v in j.scores.values())   # neutral defaults, no crash


def test_judge_compare():
    assert LLMJudge().compare(_item(), PipelineOutput(answer="A"), PipelineOutput(answer="B"),
                              answer_fn=lambda p: "winner: A\nbecause") == "A"


# --------------------------------------------------------------------- regression + gate + compare
def test_regression_direction_aware():
    deltas = {d["metric"]: d for d in compare_metrics(
        {"recall@5": 0.7, "latency_ms": 120, "hallucination_rate": 0.1},
        {"recall@5": 0.8, "latency_ms": 100, "hallucination_rate": 0.05})}
    assert deltas["recall@5"]["verdict"] == "regressed"          # lower recall = worse
    assert deltas["latency_ms"]["verdict"] == "regressed"        # higher latency = worse
    assert deltas["hallucination_rate"]["verdict"] == "regressed"  # higher hallucination = worse


def test_regression_status_and_gate():
    det = RegressionDetector()
    r = det.detect({"recall@5": 0.9}, {"recall@5": 0.8})
    assert r["status"] == "improved"
    gate = det.gate({"recall@5": 0.5, "hallucination_rate": 0.3},
                    thresholds={"recall@5": 0.6, "hallucination_rate": 0.2})
    assert gate["passed"] is False and len(gate["reasons"]) == 2


def test_pipeline_comparator():
    c = PipelineComparator().compare({"recall@5": 0.8, "latency_ms": 90},
                                     {"recall@5": 0.7, "latency_ms": 110}, a_label="new", b_label="old")
    assert c["winner"] == "new" and c["a_wins"] == 2 and c["b_wins"] == 0


# --------------------------------------------------------------------- dataset validation
def test_dataset_validation():
    validate_item({"question": "ok"})
    for bad in [{"question": ""}, {"question": "q", "difficulty": "impossible"}]:
        try:
            validate_item(bad); assert False
        except InvalidDataset:
            pass


# --------------------------------------------------------------------- cache
def test_eval_cache():
    c = EvaluationCache(capacity=2)
    assert c.get("p", "v1", 1, "i1", "q") is None and c.misses == 1
    c.put("p", "v1", 1, "i1", "q", ("out", {}))
    assert c.get("p", "v1", 1, "i1", "q") is not None and c.hits == 1
    assert c.get("p", "v2", 1, "i1", "q") is None       # version bump invalidates


# --------------------------------------------------------------------- runner (fake pipeline)
class _FakePipeline:
    name = "fake"; version = "v1"
    def run(self, ctx, item):
        rel = item.relevant_chunk_ids[0] if item.relevant_chunk_ids else "x"
        return PipelineOutput(retrieved=[RetrievedRef(chunk_id=rel, document_id="doc_x", score=0.9)],
                              answer="ans", token_usage=10, latency_ms=5)


class _Ctx:
    def __init__(self): self.services = {}


def test_runner_aggregates_and_reuses_retrieval_report():
    items = [EvalItemInput(id="i1", question="q1", relevant_chunk_ids=["doc_x:1"], relevant_document_ids=["doc_x"]),
             EvalItemInput(id="i2", question="q2", relevant_chunk_ids=["doc_x:2"], relevant_document_ids=["doc_x"])]
    res = BenchmarkRunner().run(_Ctx(), _FakePipeline(), dataset_id="ds", dataset_version=1, items=items,
                                use_cache=False)
    assert res.item_count == 2 and res.token_usage == 20
    assert "hit_rate" in res.metrics
    # recall@k / mrr came from the REUSED app.eval.RetrievalEvaluator
    assert "recall@1" in res.metrics and "mrr" in res.metrics and res.metrics["recall@1"] == 1.0
