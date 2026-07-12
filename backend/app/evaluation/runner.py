"""Benchmark Runner (Step 4) — execute a golden dataset over a pipeline and score every item.

Runs the REAL pipeline per item, computes the new metrics (MetricEngine), and — crucially — REUSES the
existing `app.eval.RetrievalEvaluator` for Recall@K / Precision@K / MRR over the already-computed outputs
(no re-execution, no duplicated retrieval-metric math). Optional LLM-judge scoring is an additional
signal. A content-addressed cache makes re-runs of an unchanged (pipeline, dataset) incremental.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.evaluation.cache import EVAL_CACHE
from app.evaluation.interfaces import BenchmarkResult, EvalItemInput, ItemResult, PipelineOutput
from app.evaluation.judge import LLMJudge
from app.evaluation.metrics import MetricEngine


@dataclass
class _RC:
    """Minimal RetrievedChunk-like for reusing app.eval.RetrievalEvaluator (needs .chunk_id + .source)."""
    chunk_id: Optional[str]
    source: Optional[str]


class BenchmarkRunner:
    def __init__(self, *, metric_engine=None, judge=None, cache=EVAL_CACHE):
        self.metric_engine = metric_engine or MetricEngine()
        self.judge = judge or LLMJudge()
        self.cache = cache

    def run(self, ctx, pipeline, *, dataset_id: str, dataset_version: int, items: List[EvalItemInput],
            model: str = "", use_judge: bool = False, use_cache: bool = True) -> BenchmarkResult:
        t0 = time.perf_counter()
        result = BenchmarkResult(pipeline=pipeline.name, pipeline_version=pipeline.version,
                                 dataset_id=dataset_id, dataset_version=dataset_version, model=model,
                                 judge_used=use_judge)
        answer_fn = ctx.services.get("answer_fn") if use_judge else None
        by_query: Dict[str, List[_RC]] = {}

        for item in items:
            cached = self.cache.get(pipeline.name, pipeline.version, dataset_version, item.id, item.question) \
                if (use_cache and not use_judge) else None
            if cached is not None:
                output, metrics = cached
                cache_hit = True
            else:
                output = pipeline.run(ctx, item)
                metrics = self.metric_engine.compute(item, output)
                cache_hit = False
                if use_cache and not use_judge:
                    self.cache.put(pipeline.name, pipeline.version, dataset_version, item.id, item.question,
                                   (output, metrics))
            judgment = self.judge.judge(item, output, answer_fn=answer_fn) if use_judge else None
            result.items.append(ItemResult(item_id=item.id, question=item.question, output=output,
                                           metrics=dict(metrics), judgment=judgment, cache_hit=cache_hit))
            by_query[item.question] = [_RC(r.chunk_id, r.document_id) for r in output.retrieved]

        result.aggregate()                                   # mean of per-item metrics first…
        self._merge_retrieval_report(result, items, by_query)  # …then add reused recall/precision/mrr
        result.duration_ms = (time.perf_counter() - t0) * 1000
        result.cost_estimate = round(result.token_usage / 1000 * 0.001, 6)
        return result

    # ------------------------------------------------------------------ REUSE app.eval for recall/precision/mrr
    @staticmethod
    def _merge_retrieval_report(result: BenchmarkResult, items: List[EvalItemInput], by_query) -> None:
        labelled = [it for it in items if it.relevant_chunk_ids or it.relevant_document_ids]
        if not labelled:
            return
        try:
            from app.eval.framework import EvalQuery, RetrievalEvaluator
            dataset = [EvalQuery(query=it.question, relevant_chunk_ids=list(it.relevant_chunk_ids),
                                 relevant_sources=list(it.relevant_document_ids)) for it in labelled]
            report = RetrievalEvaluator(dataset).evaluate(lambda q: by_query.get(q, []))
            for k, v in report.recall_at_k.items():
                result.metrics[f"recall@{k}"] = round(v, 6)
            for k, v in report.precision_at_k.items():
                result.metrics[f"precision@{k}"] = round(v, 6)
            result.metrics["mrr"] = round(report.mrr, 6)
        except Exception:
            pass  # retrieval report is additive; never fail the run
