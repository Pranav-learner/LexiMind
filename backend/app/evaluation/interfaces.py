"""Evaluation interfaces (Phase 8, Module 1) — the interface-driven benchmarking core.

Every benchmarkable subsystem is a `Pipeline` (runs the REAL production services), every metric a
`Metric`, and the optional qualitative signal a `Judge`. The runner depends only on these Protocols, so
new pipelines / metrics / judges plug in without touching it.

Value objects (dataclasses):
- `EvalItemInput`  — a golden item flattened into what a pipeline needs + what a metric scores against.
- `RetrievedRef`   — one retrieved unit (chunk/entity) with the id fields metrics match on.
- `PipelineOutput` — the uniform output every pipeline returns (retrieved + answer + citations + evidence
                     + confidence + latency/token/context telemetry).
- `ItemResult`     — the per-item scored result (output + metrics + optional judgment).
- `BenchmarkResult`— the whole run (aggregate metrics + per-item results + cost/latency).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class EvalItemInput:
    id: str
    question: str
    expected_answer: Optional[str] = None
    ground_truth: Optional[str] = None
    relevant_document_ids: List[str] = field(default_factory=list)
    relevant_chunk_ids: List[str] = field(default_factory=list)
    relevant_entities: List[str] = field(default_factory=list)
    expected_citations: List[Dict[str, Any]] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass
class RetrievedRef:
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    entity: Optional[str] = None
    source: Optional[str] = None
    score: float = 0.0


@dataclass
class PipelineOutput:
    retrieved: List[RetrievedRef] = field(default_factory=list)
    answer: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    verification: Optional[Dict[str, Any]] = None
    latency_ms: float = 0.0
    token_usage: int = 0
    context_size: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"retrieved_count": len(self.retrieved), "answer": self.answer[:600],
                "citation_count": len(self.citations), "confidence": self.confidence,
                "latency_ms": round(self.latency_ms, 3), "token_usage": self.token_usage,
                "context_size": self.context_size, "error": self.error}


@dataclass
class Judgment:
    scores: Dict[str, float] = field(default_factory=dict)   # quality/completeness/relevance/citation (0..1)
    overall: float = 0.0
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"scores": {k: round(v, 4) for k, v in self.scores.items()},
                "overall": round(self.overall, 4), "rationale": self.rationale[:400]}


@dataclass
class ItemResult:
    item_id: str
    question: str
    output: PipelineOutput
    metrics: Dict[str, float] = field(default_factory=dict)
    judgment: Optional[Judgment] = None
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"item_id": self.item_id, "question": self.question[:200], "output": self.output.to_dict(),
                "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
                "judgment": self.judgment.to_dict() if self.judgment else None, "cache_hit": self.cache_hit}


@dataclass
class BenchmarkResult:
    pipeline: str
    pipeline_version: str
    dataset_id: str
    dataset_version: int
    model: str = ""
    items: List[ItemResult] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)   # aggregate
    duration_ms: float = 0.0
    cost_estimate: float = 0.0
    token_usage: int = 0
    failed_items: int = 0
    judge_used: bool = False

    @property
    def item_count(self) -> int:
        return len(self.items)

    def aggregate(self) -> None:
        """Compute mean of every per-item metric across items (skipping missing)."""
        keys: set = set()
        for it in self.items:
            keys.update(it.metrics.keys())
        agg: Dict[str, float] = {}
        for k in keys:
            vals = [it.metrics[k] for it in self.items if k in it.metrics]
            if vals:
                agg[k] = round(mean(vals), 6)
        if self.judge_used:
            jv = [it.judgment.overall for it in self.items if it.judgment]
            if jv:
                agg["judge_overall"] = round(mean(jv), 6)
        self.metrics = agg
        self.token_usage = sum(it.output.token_usage for it in self.items)
        self.failed_items = sum(1 for it in self.items if it.output.error)

    def to_dict(self, *, include_items: bool = True) -> Dict[str, Any]:
        d = {"pipeline": self.pipeline, "pipeline_version": self.pipeline_version,
             "dataset_id": self.dataset_id, "dataset_version": self.dataset_version, "model": self.model,
             "item_count": self.item_count, "failed_items": self.failed_items, "metrics": self.metrics,
             "duration_ms": round(self.duration_ms, 3), "cost_estimate": round(self.cost_estimate, 4),
             "token_usage": self.token_usage, "judge_used": self.judge_used}
        if include_items:
            d["items"] = [it.to_dict() for it in self.items]
        return d


# --------------------------------------------------------------------- protocols
class Pipeline(Protocol):
    name: str
    version: str
    def run(self, ctx, item: EvalItemInput) -> PipelineOutput: ...


class Metric(Protocol):
    name: str
    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]: ...


class Judge(Protocol):
    def judge(self, item: EvalItemInput, output: PipelineOutput, *, answer_fn=None) -> Judgment: ...
