"""AI Evaluation & Benchmarking Framework (Phase 8, Module 1) — LexiMind becomes measurable.

Offline/online evaluation over golden datasets: a `BenchmarkRunner` executes the REAL production
pipelines (retrieval / graph retrieval / temporal / full answer), a `MetricEngine` scores each item
(REUSING `app.eval.RetrievalEvaluator` for Recall@K/Precision@K/MRR and adding NDCG/MAP/citation/ground-
truth/hallucination/efficiency), an optional `LLMJudge` (reuses the single answer_fn) adds a qualitative
signal, and a `RegressionDetector` + `PipelineComparator` turn runs into CI quality gates + A/B reports.
Every run is a reproducible `EvaluationRunLog`. No AI pipeline is duplicated — evaluation runs production.

    models.py      EvalDataset / EvalItem / EvaluationRunLog
    interfaces.py  Pipeline/Metric/Judge protocols + value objects
    datasets.py    DatasetManager (create/import/export/version/validate)
    pipelines.py   benchmarkable pipelines (run the real services)
    metrics.py     MetricEngine (new metrics; recall/precision/mrr reused from app.eval)
    judge.py       LLMJudge (reuses answer_fn; A/B compare)
    runner.py      BenchmarkRunner (+ retrieval-report reuse + cache)
    regression.py  RegressionDetector + PipelineComparator + CI gate
    cache.py       EvaluationCache (incremental re-runs)
    repository/service/schemas/api  data access + orchestration + DTOs + routes
"""
