"""Evaluation service — orchestrate benchmarks + persist reproducible runs + regression/comparison.

Coordinates the DatasetManager, BenchmarkRunner (which executes the REAL pipelines + reuses the metric
framework), RegressionDetector, and PipelineComparator; persists an `EvaluationRunLog` per run
(auto-detecting regression vs the previous run of the same pipeline+dataset, and evaluating a CI gate).
Contains no metric/pipeline logic — that lives in the injectable engines.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.evaluation.cache import EVAL_CACHE
from app.evaluation.datasets import DatasetManager
from app.evaluation.errors import DatasetNotFound, RunNotFound
from app.evaluation.interfaces import BenchmarkResult
from app.evaluation.models import EvaluationRunLog
from app.evaluation.pipelines import EvalContext, get_pipeline, list_pipelines
from app.evaluation.regression import PipelineComparator, RegressionDetector
from app.evaluation.repository import EvaluationRepository
from app.evaluation.runner import BenchmarkRunner


class EvaluationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = EvaluationRepository(db)
        self.datasets = DatasetManager(db)
        self.runner = BenchmarkRunner()
        self.regression = RegressionDetector()
        self.comparator = PipelineComparator()

    # ------------------------------------------------------------------ datasets
    def create_dataset(self, owner_id, workspace_id, **kw) -> Dict[str, Any]:
        ds = self.datasets.create(owner_id, workspace_id, **kw)
        return self._dataset_dict(ds)

    def import_dataset(self, owner_id, workspace_id, payload: Dict[str, Any]) -> Dict[str, Any]:
        ds = self.datasets.create(owner_id, workspace_id, name=payload.get("name", "imported"),
                                  description=payload.get("description"), tags=payload.get("tags"),
                                  items=payload.get("items", []))
        return self._dataset_dict(ds)

    def export_dataset(self, owner_id, dataset_id: str) -> Dict[str, Any]:
        return self.datasets.export(dataset_id, owner_id)

    def list_datasets(self, workspace_id, owner_id) -> List[Dict[str, Any]]:
        return [self._dataset_dict(d) for d in self.repo.datasets(workspace_id, owner_id)]

    def pipelines(self) -> List[Dict[str, str]]:
        return list_pipelines()

    # ------------------------------------------------------------------ run benchmark
    def run_benchmark(self, owner_id: str, workspace_id: str, *, dataset_id: str, pipeline: str,
                      services: Dict[str, Any], use_judge: bool = False, label: Optional[str] = None,
                      thresholds: Optional[Dict[str, float]] = None, use_cache: bool = True) -> Dict[str, Any]:
        ds = self.repo.get_dataset(dataset_id, owner_id)
        if ds is None or ds.workspace_id != workspace_id:
            raise DatasetNotFound(dataset_id)
        pipe = get_pipeline(pipeline)
        items = self.datasets.load_inputs(dataset_id)
        ctx = EvalContext(db=self.db, workspace_id=workspace_id, owner_id=owner_id, services=services)
        model = services.get("model", "fake" if services.get("answer_fn") else "")
        result: BenchmarkResult = self.runner.run(ctx, pipe, dataset_id=dataset_id,
                                                  dataset_version=ds.version, items=items, model=model,
                                                  use_judge=use_judge, use_cache=use_cache)

        # regression vs the previous run of the same pipeline+dataset (auto-baseline)
        baseline = self.repo.latest_run(workspace_id, owner_id, dataset_id=dataset_id, pipeline=pipeline)
        regression = None
        baseline_metrics = (baseline.metrics or {}) if baseline else {}
        if baseline_metrics:
            regression = self.regression.detect(result.metrics, baseline_metrics)
        gate = self.regression.gate(result.metrics, baseline_metrics or None, thresholds=thresholds)

        run = EvaluationRunLog(
            id=f"evr_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            dataset_id=dataset_id, dataset_version=ds.version, pipeline=pipeline,
            pipeline_version=pipe.version, model=model, label=label, status="completed",
            metrics=result.metrics, item_count=result.item_count, failed_items=result.failed_items,
            duration_ms=result.duration_ms, cost_estimate=result.cost_estimate,
            token_usage=result.token_usage, judge_used=use_judge,
            baseline_run_id=(baseline.id if baseline else None),
            regression_status=(regression["status"] if regression else "none"),
            gate_passed=gate["passed"],
            report={"items": [it.to_dict() for it in result.items], "regression": regression, "gate": gate})
        self.repo.save_run(run)
        return {**self._run_dict(run), "regression": regression, "gate": gate,
                "items": run.report["items"]}

    # ------------------------------------------------------------------ history / regression / comparison
    def history(self, workspace_id, owner_id, *, dataset_id=None, pipeline=None) -> List[Dict[str, Any]]:
        return [self._run_dict(r) for r in self.repo.runs(workspace_id, owner_id, dataset_id=dataset_id,
                                                          pipeline=pipeline)]

    def get_run(self, run_id: str, owner_id: str) -> Dict[str, Any]:
        run = self.repo.get_run(run_id, owner_id)
        if run is None:
            raise RunNotFound(run_id)
        return {**self._run_dict(run), "report": run.report}

    def regression_report(self, run_id: str, owner_id: str, *,
                          baseline_run_id: Optional[str] = None) -> Dict[str, Any]:
        run = self.repo.get_run(run_id, owner_id)
        if run is None:
            raise RunNotFound(run_id)
        if baseline_run_id:
            base = self.repo.get_run(baseline_run_id, owner_id)
            if base is None:
                raise RunNotFound(baseline_run_id)
        else:
            base = self.repo.get_run(run.baseline_run_id, owner_id) if run.baseline_run_id else None
        if base is None:
            return {"status": "none", "detail": "no baseline run available"}
        return {"run": run.id, "baseline": base.id,
                **self.regression.detect(run.metrics or {}, base.metrics or {})}

    def compare(self, a_run_id: str, b_run_id: str, owner_id: str) -> Dict[str, Any]:
        a = self.repo.get_run(a_run_id, owner_id); b = self.repo.get_run(b_run_id, owner_id)
        if a is None:
            raise RunNotFound(a_run_id)
        if b is None:
            raise RunNotFound(b_run_id)
        return {"a": self._run_dict(a), "b": self._run_dict(b),
                "comparison": self.comparator.compare(a.metrics or {}, b.metrics or {},
                                                      a_label=a.label or a.pipeline,
                                                      b_label=b.label or b.pipeline)}

    def dashboard(self, workspace_id, owner_id) -> Dict[str, Any]:
        runs = self.repo.runs(workspace_id, owner_id, limit=100)
        return {"total_runs": len(runs), "datasets": len(self.repo.datasets(workspace_id, owner_id)),
                "regressions": sum(1 for r in runs if r.regression_status == "regressed"),
                "gate_failures": sum(1 for r in runs if r.gate_passed is False),
                "recent": [self._run_dict(r) for r in runs[:20]], "cache": EVAL_CACHE.stats()}

    # ------------------------------------------------------------------ serialization
    @staticmethod
    def _dataset_dict(ds) -> Dict[str, Any]:
        return {"id": ds.id, "name": ds.name, "version": ds.version, "description": ds.description,
                "tags": ds.tags or [], "item_count": ds.item_count,
                "difficulty_distribution": ds.difficulty_distribution or {}}

    @staticmethod
    def _run_dict(r) -> Dict[str, Any]:
        return {"id": r.id, "dataset_id": r.dataset_id, "dataset_version": r.dataset_version,
                "pipeline": r.pipeline, "pipeline_version": r.pipeline_version, "model": r.model,
                "label": r.label, "status": r.status, "metrics": r.metrics or {}, "item_count": r.item_count,
                "failed_items": r.failed_items, "duration_ms": round(r.duration_ms, 3),
                "cost_estimate": r.cost_estimate, "token_usage": r.token_usage, "judge_used": r.judge_used,
                "baseline_run_id": r.baseline_run_id, "regression_status": r.regression_status,
                "gate_passed": r.gate_passed, "created_at": r.created_at.isoformat() if r.created_at else None}
