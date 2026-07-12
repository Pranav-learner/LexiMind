"""Metric Engine (Step 5) — production-grade, interface-driven metrics.

Retrieval Recall@K / Precision@K / MRR are computed by REUSING `app.eval.RetrievalEvaluator` at the
aggregate level (see runner) — not re-implemented here. This module adds the metrics that framework
lacks, each as a small `Metric` (so custom metrics plug in): NDCG@K, MAP, Hit-Rate, Citation Accuracy,
Ground-Truth Match (reuses the Module-3 lexical coverage), Evidence Coverage, Hallucination Rate +
Verification Score (reuse the Verification Engine's output), and efficiency (latency / tokens / context).
"""

from __future__ import annotations

import math
from typing import Dict, List, Set

from app.evaluation.interfaces import EvalItemInput, PipelineOutput
from app.reasoning.textutil import coverage

K_VALUES = (1, 3, 5, 10)


def _relevant_set(item: EvalItemInput) -> Set[str]:
    return set(item.relevant_chunk_ids) | set(item.relevant_document_ids) | set(item.relevant_entities)


def _is_relevant(ref, relevant: Set[str]) -> bool:
    return any(x in relevant for x in (ref.chunk_id, ref.document_id, ref.entity) if x)


class RankingMetrics:
    """NDCG@K, MAP, Hit-Rate — ranking-quality signals RetrievalEvaluator does not cover."""
    name = "ranking"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        relevant = _relevant_set(item)
        if not relevant or not output.retrieved:
            return {}
        rels = [1 if _is_relevant(r, relevant) else 0 for r in output.retrieved]
        out: Dict[str, float] = {}
        out["hit_rate"] = 1.0 if any(rels) else 0.0
        # MAP over the retrieved list
        hits = 0; precisions = []
        for i, rel in enumerate(rels, start=1):
            if rel:
                hits += 1; precisions.append(hits / i)
        out["map"] = round(sum(precisions) / min(len(relevant), len(rels)), 6) if precisions else 0.0
        # NDCG@k
        for k in K_VALUES:
            dcg = sum(rel / math.log2(i + 1) for i, rel in enumerate(rels[:k], start=1))
            ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
            out[f"ndcg@{k}"] = round(dcg / ideal, 6) if ideal else 0.0
        return out


class CitationAccuracy:
    name = "citation"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        expected_docs = {c.get("document_id") for c in item.expected_citations if c.get("document_id")}
        expected_docs |= set(item.relevant_document_ids)
        if not expected_docs or not output.citations:
            if output.answer and expected_docs and not output.citations:
                return {"citation_accuracy": 0.0}   # expected citations but produced none
            return {}
        produced = {c.get("document_id") for c in output.citations if c.get("document_id")}
        if not produced:
            return {"citation_accuracy": 0.0}
        correct = len(produced & expected_docs)
        return {"citation_accuracy": round(correct / len(produced), 6)}


class GroundTruthMatch:
    """Lexical answer match against expected_answer/ground_truth (reuses Module-3 coverage)."""
    name = "ground_truth"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        target = item.expected_answer or item.ground_truth
        if not target or not output.answer:
            return {}
        # bidirectional: how much of the expected answer the produced answer covers
        return {"ground_truth_match": round(coverage(target, output.answer), 6)}


class EvidenceCoverage:
    name = "evidence"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        if not output.answer:
            return {}
        # fraction of the retrieved evidence actually surfaced as citations (grounding density)
        n = max(1, len(output.retrieved))
        return {"evidence_coverage": round(min(1.0, len(output.citations) / n), 6)}


class VerificationMetrics:
    """Hallucination rate + verification score from the reused Verification Engine output."""
    name = "verification"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        v = output.verification
        if not v:
            return {}
        out: Dict[str, float] = {}
        conf = (v.get("confidence") or {})
        if isinstance(conf, dict) and conf.get("overall") is not None:
            out["verification_score"] = round(float(conf["overall"]), 6)
        counts = v.get("counts") or {}
        total = sum(counts.values()) if counts else 0
        if total:
            bad = counts.get("unsupported", 0) + counts.get("conflicting", 0)
            out["hallucination_rate"] = round(bad / total, 6)
        return out


class EfficiencyMetrics:
    name = "efficiency"

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        out = {"latency_ms": round(output.latency_ms, 3), "token_usage": float(output.token_usage),
               "context_size": float(output.context_size)}
        return out


DEFAULT_METRICS = [RankingMetrics(), CitationAccuracy(), GroundTruthMatch(), EvidenceCoverage(),
                   VerificationMetrics(), EfficiencyMetrics()]


class MetricEngine:
    def __init__(self, metrics=None):
        self.metrics = metrics or DEFAULT_METRICS

    def compute(self, item: EvalItemInput, output: PipelineOutput) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for m in self.metrics:
            try:
                out.update(m.compute(item, output))
            except Exception:
                continue
        return out
