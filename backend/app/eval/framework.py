"""Retrieval evaluation: Recall@K, Precision@K, MRR, and latency.

WHY (per MASTER_CONTEXT, evals are MANDATORY):
- "Evals are required before claiming improvements." This framework makes retrieval
  quality measurable so the dense-only baseline and the Phase-1 hybrid+rerank pipeline
  can be compared on the same ground-truth set, rather than by vibes.

A ground-truth item is a query plus the set of chunk_ids (and/or sources) that a human
considers relevant. The evaluator runs ANY retrieve function (query -> ranked
List[RetrievedChunk]) so it can score the dense retriever, BM25, hybrid, or the full
pipeline interchangeably.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Callable, Dict, List, Optional, Sequence

from app.retrieval.schemas import RetrievedChunk

RetrieveFn = Callable[[str], List[RetrievedChunk]]


@dataclass
class EvalQuery:
    query: str
    relevant_chunk_ids: List[str] = field(default_factory=list)
    relevant_sources: List[str] = field(default_factory=list)

    def is_relevant(self, chunk: RetrievedChunk) -> bool:
        if self.relevant_chunk_ids and chunk.chunk_id in set(self.relevant_chunk_ids):
            return True
        if self.relevant_sources and chunk.source in set(self.relevant_sources):
            return True
        return False

    @property
    def num_relevant(self) -> int:
        # Source-level ground truth has unknown cardinality; fall back to chunk-level.
        return len(self.relevant_chunk_ids) if self.relevant_chunk_ids else 1


@dataclass
class EvalReport:
    k_values: List[int]
    recall_at_k: Dict[int, float]
    precision_at_k: Dict[int, float]
    mrr: float
    latency_ms: Dict[str, float]  # mean / p50 / p95
    num_queries: int
    per_query: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "num_queries": self.num_queries,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "mrr": self.mrr,
            "latency_ms": self.latency_ms,
        }

    def to_markdown(self, title: str = "Retrieval Evaluation Report") -> str:
        lines = [f"# {title}", "", f"- Queries evaluated: **{self.num_queries}**", ""]
        lines.append("| K | Recall@K | Precision@K |")
        lines.append("|---|----------|-------------|")
        for k in self.k_values:
            lines.append(f"| {k} | {self.recall_at_k[k]:.4f} | {self.precision_at_k[k]:.4f} |")
        lines += [
            "",
            f"- **MRR**: {self.mrr:.4f}",
            "",
            "## Latency",
            "",
            f"- mean: {self.latency_ms['mean']:.1f} ms",
            f"- p50: {self.latency_ms['p50']:.1f} ms",
            f"- p95: {self.latency_ms['p95']:.1f} ms",
        ]
        return "\n".join(lines)


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


class RetrievalEvaluator:
    def __init__(self, dataset: Sequence[EvalQuery], k_values: Sequence[int] = (1, 3, 5, 10)):
        if not dataset:
            raise ValueError("dataset must contain at least one EvalQuery")
        self.dataset = list(dataset)
        self.k_values = sorted(set(k_values))

    def evaluate(self, retrieve_fn: RetrieveFn) -> EvalReport:
        max_k = max(self.k_values)
        recall_acc: Dict[int, List[float]] = {k: [] for k in self.k_values}
        precision_acc: Dict[int, List[float]] = {k: [] for k in self.k_values}
        rr_acc: List[float] = []
        latencies: List[float] = []
        per_query: List[dict] = []

        for item in self.dataset:
            t0 = time.perf_counter()
            results = retrieve_fn(item.query)
            latency = (time.perf_counter() - t0) * 1000
            latencies.append(latency)

            results = results[:max_k]
            relevance = [item.is_relevant(c) for c in results]

            # Reciprocal rank of the first relevant hit.
            rr = 0.0
            for rank, rel in enumerate(relevance, start=1):
                if rel:
                    rr = 1.0 / rank
                    break
            rr_acc.append(rr)

            q_recall: Dict[int, float] = {}
            q_precision: Dict[int, float] = {}
            for k in self.k_values:
                hits = sum(relevance[:k])
                # Clamp the recall numerator: with chunk-level GT, hits <= num_relevant
                # naturally; with source-level GT (num_relevant == 1) a query may match
                # several chunks from the right doc, so this caps recall at 1.0 and makes
                # source-level recall behave as success@k.
                q_recall[k] = min(hits, item.num_relevant) / item.num_relevant if item.num_relevant else 0.0
                q_precision[k] = hits / k
                recall_acc[k].append(q_recall[k])
                precision_acc[k].append(q_precision[k])

            per_query.append({
                "query": item.query,
                "rr": rr,
                "recall": q_recall,
                "precision": q_precision,
                "latency_ms": latency,
            })

        return EvalReport(
            k_values=self.k_values,
            recall_at_k={k: mean(recall_acc[k]) for k in self.k_values},
            precision_at_k={k: mean(precision_acc[k]) for k in self.k_values},
            mrr=mean(rr_acc) if rr_acc else 0.0,
            latency_ms={
                "mean": mean(latencies) if latencies else 0.0,
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
            },
            num_queries=len(self.dataset),
            per_query=per_query,
        )


def load_dataset(path: str) -> List[EvalQuery]:
    """Load a ground-truth dataset from JSON.

    Expected shape:
        [
          {"query": "...", "relevant_chunk_ids": ["doc_x:3", ...]},
          {"query": "...", "relevant_sources": ["javabook.pdf"]}
        ]
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    dataset: List[EvalQuery] = []
    for item in raw:
        dataset.append(
            EvalQuery(
                query=item["query"],
                relevant_chunk_ids=item.get("relevant_chunk_ids", []) or [],
                relevant_sources=item.get("relevant_sources", []) or [],
            )
        )
    return dataset
