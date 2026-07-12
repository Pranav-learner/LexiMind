"""Pipeline Metrics (Step 6) — counters / histograms / timers / gauges over the unified telemetry.

Aggregates the normalized `TelemetryEvent` stream into the operational metrics the dashboard + alerts
consume: request volume (counter), error rate (gauge), latency distribution p50/p95/p99 (histogram/timer),
throughput, and a per-source breakdown. Pure computation over the unifier's read-only view — it recomputes
nothing the source logs already own.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Sequence

from app.observability.interfaces import TelemetryEvent

_ERROR_STATUSES = {"failed", "error", "cancelled"}


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 3)


def _latency_hist(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {"count": len(values), "mean": round(mean(values), 3), "p50": _percentile(values, 50),
            "p95": _percentile(values, 95), "p99": _percentile(values, 99), "max": round(max(values), 3)}


class MetricsCollector:
    def summarize(self, events: List[TelemetryEvent]) -> Dict[str, Any]:
        total = len(events)
        errors = sum(1 for e in events if e.status in _ERROR_STATUSES)
        lat = [e.latency_ms for e in events if e.latency_ms > 0]

        by_source: Dict[str, Dict[str, Any]] = {}
        for e in events:
            b = by_source.setdefault(e.source, {"count": 0, "errors": 0, "latencies": [], "tokens": 0, "cost": 0.0})
            b["count"] += 1
            b["tokens"] += e.tokens
            b["cost"] += e.cost
            if e.status in _ERROR_STATUSES:
                b["errors"] += 1
            if e.latency_ms > 0:
                b["latencies"].append(e.latency_ms)
        for src, b in by_source.items():
            lats = b.pop("latencies")
            b["mean_ms"] = round(mean(lats), 3) if lats else 0.0
            b["p95_ms"] = _percentile(lats, 95)
            b["error_rate"] = round(b["errors"] / b["count"], 4) if b["count"] else 0.0
            b["cost"] = round(b["cost"], 6)

        return {
            "requests": total,                              # counter
            "errors": errors,
            "error_rate": round(errors / total, 4) if total else 0.0,   # gauge
            "latency_ms": _latency_hist(lat),               # histogram / timer
            "tokens_total": sum(e.tokens for e in events),
            "cost_total": round(sum(e.cost for e in events), 6),
            "by_source": by_source,
        }

    def flat_metrics(self, events: List[TelemetryEvent]) -> Dict[str, float]:
        """A flat metric map for alert-rule evaluation."""
        s = self.summarize(events)
        return {"requests": float(s["requests"]), "error_rate": s["error_rate"],
                "p95_latency_ms": s["latency_ms"]["p95"], "p99_latency_ms": s["latency_ms"]["p99"],
                "mean_latency_ms": s["latency_ms"]["mean"], "total_cost": s["cost_total"],
                "total_tokens": float(s["tokens_total"])}
