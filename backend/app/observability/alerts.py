"""Alerting System (Step 8) — configurable threshold rules over the live metrics.

A rule fires when a flat metric crosses its threshold in the wrong direction (`gt`/`lt`). Built-in rules
cover the common failure modes (latency spike, high error rate, cost/token explosion); workspace-scoped
custom `AlertRule`s extend them. Fired alerts persist as `AlertEvent`s. Channels (Slack/webhook/email/
PagerDuty) are a declared future field — the rule + event shape is already channel-ready.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

# built-in rules (metric, comparator, threshold, severity, human message)
DEFAULT_RULES = [
    {"name": "Latency spike (p95)", "metric": "p95_latency_ms", "comparator": "gt", "threshold": 8000.0, "severity": "warning"},
    {"name": "High error rate", "metric": "error_rate", "comparator": "gt", "threshold": 0.20, "severity": "critical"},
    {"name": "Cost explosion", "metric": "total_cost", "comparator": "gt", "threshold": 50.0, "severity": "warning"},
    {"name": "Token explosion", "metric": "total_tokens", "comparator": "gt", "threshold": 5_000_000.0, "severity": "warning"},
]


def _fires(value: float, comparator: str, threshold: float) -> bool:
    return value > threshold if comparator == "gt" else value < threshold


class AlertEngine:
    name = "alert-engine-v1"

    def evaluate(self, metrics: Dict[str, float], rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fired: List[Dict[str, Any]] = []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            val = metrics.get(rule["metric"])
            if val is None:
                continue
            if _fires(val, rule.get("comparator", "gt"), float(rule["threshold"])):
                fired.append({
                    "rule_id": rule.get("id"), "rule_name": rule.get("name", rule["metric"]),
                    "metric": rule["metric"], "value": round(val, 4), "threshold": float(rule["threshold"]),
                    "comparator": rule.get("comparator", "gt"), "severity": rule.get("severity", "warning"),
                    "message": f"{rule.get('name', rule['metric'])}: {rule['metric']} = {val:.4g} "
                               f"{'>' if rule.get('comparator', 'gt') == 'gt' else '<'} {rule['threshold']}"})
        return fired

    @staticmethod
    def new_event(workspace_id: str, owner_id: str, fired: Dict[str, Any]):
        from app.observability.models import AlertEvent
        return AlertEvent(id=f"ale_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                          rule_id=fired.get("rule_id") or "builtin", metric=fired["metric"],
                          value=fired["value"], threshold=fired["threshold"], severity=fired["severity"],
                          message=fired["message"][:2000])
