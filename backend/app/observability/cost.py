"""Token & Cost Tracking (Step 5) — accounting over the unified telemetry.

Aggregates token usage + estimated cost across every source that reports them (agent runs, agent tasks,
orchestrations, evaluations, traces), broken down per source/operation (≈ per agent / pipeline / tool)
and per workspace. Reuses the numbers each module already recorded — no separate cost log. Multi-provider
billing is a future field (`provider`) behind the same shape.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.observability.interfaces import TelemetryEvent


class CostTracker:
    def report(self, events: List[TelemetryEvent]) -> Dict[str, Any]:
        total_tokens = sum(e.tokens for e in events)
        total_cost = round(sum(e.cost for e in events), 6)

        by_source: Dict[str, Dict[str, float]] = {}
        by_operation: Dict[str, Dict[str, float]] = {}
        for e in events:
            if e.tokens == 0 and e.cost == 0.0:
                continue
            bs = by_source.setdefault(e.source, {"tokens": 0, "cost": 0.0, "count": 0})
            bs["tokens"] += e.tokens; bs["cost"] += e.cost; bs["count"] += 1
            key = f"{e.source}:{e.operation}" if e.operation else e.source
            bo = by_operation.setdefault(key, {"tokens": 0, "cost": 0.0, "count": 0})
            bo["tokens"] += e.tokens; bo["cost"] += e.cost; bo["count"] += 1

        for d in list(by_source.values()) + list(by_operation.values()):
            d["cost"] = round(d["cost"], 6)

        counted = sum(1 for e in events if e.tokens or e.cost)
        top_ops = sorted(by_operation.items(), key=lambda kv: kv[1]["cost"], reverse=True)[:10]
        return {
            "total_tokens": total_tokens, "total_cost": total_cost,
            "avg_tokens_per_request": round(total_tokens / counted, 2) if counted else 0.0,
            "avg_cost_per_request": round(total_cost / counted, 6) if counted else 0.0,
            "by_source": by_source,
            "top_cost_operations": [{"operation": k, **v} for k, v in top_ops],
        }
