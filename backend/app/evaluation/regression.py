"""Regression Detection (Step 7) + Pipeline Comparison (Step 8) — CI-ready quality gates.

Compares a run's aggregate metrics against a baseline: each metric is classified higher-is-better (recall/
precision/mrr/ndcg/map/hit_rate/citation/ground_truth/verification/judge) or lower-is-better (latency/
tokens/context/cost/hallucination). A change beyond a tolerance in the WRONG direction is a regression;
in the right direction, an improvement. The overall `regression_status` + a threshold `gate` make this
usable as a CI quality gate. Comparison (A vs B) uses the same per-metric winner logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

LOWER_IS_BETTER = {"latency_ms", "token_usage", "context_size", "cost_estimate", "hallucination_rate"}
DEFAULT_TOLERANCE = 0.02   # 2% — changes smaller than this are "stable"


def _direction(metric: str) -> int:
    return -1 if metric in LOWER_IS_BETTER else 1


def compare_metrics(current: Dict[str, float], baseline: Dict[str, float], *,
                    tolerance: float = DEFAULT_TOLERANCE) -> List[Dict[str, Any]]:
    deltas: List[Dict[str, Any]] = []
    for metric in sorted(set(current) | set(baseline)):
        cur = current.get(metric)
        base = baseline.get(metric)
        if cur is None or base is None:
            continue
        direction = _direction(metric)
        raw = cur - base
        rel = raw / abs(base) if base else (0.0 if raw == 0 else raw)
        signed = rel * direction     # >0 = better, <0 = worse (accounts for lower-is-better)
        if abs(rel) < tolerance:
            verdict = "stable"
        elif signed > 0:
            verdict = "improved"
        else:
            verdict = "regressed"
        deltas.append({"metric": metric, "current": round(cur, 6), "baseline": round(base, 6),
                       "delta": round(raw, 6), "rel_change": round(rel, 6), "verdict": verdict})
    return deltas


class RegressionDetector:
    name = "regression-v1"

    def detect(self, current: Dict[str, float], baseline: Dict[str, float], *,
               tolerance: float = DEFAULT_TOLERANCE) -> Dict[str, Any]:
        deltas = compare_metrics(current, baseline, tolerance=tolerance)
        regressed = [d for d in deltas if d["verdict"] == "regressed"]
        improved = [d for d in deltas if d["verdict"] == "improved"]
        status = "regressed" if regressed else ("improved" if improved else "stable")
        return {"status": status, "regressed": regressed, "improved": improved,
                "deltas": deltas, "regression_count": len(regressed), "improvement_count": len(improved)}

    def gate(self, current: Dict[str, float], baseline: Optional[Dict[str, float]] = None, *,
             thresholds: Optional[Dict[str, float]] = None, tolerance: float = DEFAULT_TOLERANCE) -> Dict[str, Any]:
        """CI quality gate: fail on any regression vs baseline OR any absolute-threshold violation."""
        reasons: List[str] = []
        if baseline:
            reg = self.detect(current, baseline, tolerance=tolerance)
            for d in reg["regressed"]:
                reasons.append(f"{d['metric']} regressed {d['rel_change']:+.1%}")
        for metric, minimum in (thresholds or {}).items():
            val = current.get(metric)
            if val is None:
                continue
            if metric in LOWER_IS_BETTER:
                if val > minimum:
                    reasons.append(f"{metric} {val:.4g} exceeds max {minimum}")
            elif val < minimum:
                reasons.append(f"{metric} {val:.4g} below min {minimum}")
        return {"passed": not reasons, "reasons": reasons}


class PipelineComparator:
    """A/B comparison of two runs (retriever vs retriever, prompt vs prompt, model vs model)."""
    name = "comparator-v1"

    def compare(self, a_metrics: Dict[str, float], b_metrics: Dict[str, float], *,
                a_label: str = "A", b_label: str = "B") -> Dict[str, Any]:
        deltas = compare_metrics(a_metrics, b_metrics)   # A relative to B
        a_wins = sum(1 for d in deltas if d["verdict"] == "improved")
        b_wins = sum(1 for d in deltas if d["verdict"] == "regressed")
        winner = a_label if a_wins > b_wins else b_label if b_wins > a_wins else "tie"
        return {"a_label": a_label, "b_label": b_label, "winner": winner,
                "a_wins": a_wins, "b_wins": b_wins, "per_metric": deltas}
