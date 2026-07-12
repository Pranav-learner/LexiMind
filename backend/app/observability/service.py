"""Observability service — the unified operations layer.

Composes the unifier (read existing telemetry), the metrics collector, cost tracker, health monitor, and
alert engine into trace/metrics/cost/health/alerts/dashboard views. Also owns the distributed-trace reads
+ alert-rule CRUD + the instrumented `traced_query`. It re-persists NOTHING that the source logs own; the
only writes are new traces (tracer) and fired alert events.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.observability.alerts import DEFAULT_RULES, AlertEngine
from app.observability.cost import CostTracker
from app.observability.errors import RuleNotFound, TraceNotFound
from app.observability.health import HealthMonitor
from app.observability.metrics import MetricsCollector
from app.observability.models import AlertRule
from app.observability.repository import ObservabilityRepository
from app.observability.unifier import TelemetryUnifier


class ObservabilityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ObservabilityRepository(db)
        self.unifier = TelemetryUnifier(db)
        self.metrics = MetricsCollector()
        self.cost = CostTracker()
        self.health = HealthMonitor()
        self.alerts = AlertEngine()

    # ------------------------------------------------------------------ telemetry feed + metrics
    def events(self, workspace_id, owner_id, *, source=None, limit=200) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.unifier.events(workspace_id, owner_id, source=source, limit=limit)]

    def metrics_summary(self, workspace_id, owner_id) -> Dict[str, Any]:
        events = self.unifier.events(workspace_id, owner_id, limit=1000)
        return {**self.metrics.summarize(events), "by_source_totals": self.unifier.by_source_counts(workspace_id, owner_id)}

    def cost_report(self, workspace_id, owner_id) -> Dict[str, Any]:
        events = self.unifier.events(workspace_id, owner_id, limit=2000)
        return self.cost.report(events)

    def health_summary(self, workspace_id, owner_id) -> Dict[str, Any]:
        events = self.unifier.events(workspace_id, owner_id, limit=500)
        err = self.metrics.summarize(events)["error_rate"]
        return self.health.summary(self.db, workspace_id, owner_id, error_rate=err)

    # ------------------------------------------------------------------ distributed traces
    def traces(self, workspace_id, owner_id, *, limit=50) -> List[Dict[str, Any]]:
        return [self._trace_row(t) for t in self.repo.traces(workspace_id, owner_id, limit=limit)]

    def trace_detail(self, trace_id, owner_id) -> Dict[str, Any]:
        t = self.repo.get_trace(trace_id, owner_id)
        if t is None:
            raise TraceNotFound(trace_id)
        spans = self.repo.spans_for(trace_id)
        return {**self._trace_row(t), "spans": [self._span_row(s) for s in spans],
                "waterfall": self._waterfall(spans)}

    def run_traced_query(self, workspace_id, owner_id, *, question, services, hops=2) -> Dict[str, Any]:
        from app.observability.instrument import traced_query
        out = traced_query(self.db, workspace_id, owner_id, question=question, services=services, hops=hops)
        return {**out, **self.trace_detail(out["trace_id"], owner_id)}

    # ------------------------------------------------------------------ alerts
    def create_rule(self, owner_id, workspace_id, *, name, metric, comparator, threshold, severity) -> Dict[str, Any]:
        rule = AlertRule(id=f"alr_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                         name=name, metric=metric, comparator=comparator, threshold=threshold, severity=severity)
        self.repo.create_rule(rule)
        return self._rule_row(rule)

    def rules(self, workspace_id, owner_id) -> List[Dict[str, Any]]:
        return [self._rule_row(r) for r in self.repo.rules(workspace_id, owner_id)]

    def delete_rule(self, rule_id, owner_id) -> None:
        if not self.repo.delete_rule(rule_id, owner_id):
            raise RuleNotFound(rule_id)

    def evaluate_alerts(self, workspace_id, owner_id, *, persist: bool = True) -> Dict[str, Any]:
        events = self.unifier.events(workspace_id, owner_id, limit=1000)
        flat = self.metrics.flat_metrics(events)
        rules = list(DEFAULT_RULES) + [self._rule_row(r) for r in self.repo.rules(workspace_id, owner_id)]
        fired = self.alerts.evaluate(flat, rules)
        if persist and fired:
            self.repo.save_events([self.alerts.new_event(workspace_id, owner_id, f) for f in fired])
        return {"metrics": flat, "fired": fired, "fired_count": len(fired)}

    def alert_history(self, workspace_id, owner_id, *, limit=50) -> List[Dict[str, Any]]:
        return [{"id": e.id, "rule_id": e.rule_id, "metric": e.metric, "value": e.value,
                 "threshold": e.threshold, "severity": e.severity, "message": e.message,
                 "created_at": e.created_at.isoformat() if e.created_at else None}
                for e in self.repo.recent_events(workspace_id, owner_id, limit=limit)]

    # ------------------------------------------------------------------ dashboard
    def dashboard(self, workspace_id, owner_id) -> Dict[str, Any]:
        events = self.unifier.events(workspace_id, owner_id, limit=1000)
        summary = self.metrics.summarize(events)
        flat = self.metrics.flat_metrics(events)
        fired = self.alerts.evaluate(flat, list(DEFAULT_RULES))
        return {"metrics": summary, "cost": self.cost.report(events),
                "health": self.health.summary(self.db, workspace_id, owner_id, error_rate=summary["error_rate"]),
                "active_alerts": fired,
                "recent_traces": [self._trace_row(t) for t in self.repo.traces(workspace_id, owner_id, limit=10)],
                "recent_events": [e.to_dict() for e in events[:15]]}

    # ------------------------------------------------------------------ serialization
    @staticmethod
    def _trace_row(t) -> Dict[str, Any]:
        return {"id": t.id, "operation": t.operation, "status": t.status, "total_ms": round(t.total_ms, 3),
                "span_count": t.span_count, "token_usage": t.token_usage, "cost_estimate": t.cost_estimate,
                "error": t.error, "created_at": t.created_at.isoformat() if t.created_at else None}

    @staticmethod
    def _span_row(s) -> Dict[str, Any]:
        return {"id": s.id, "parent_span_id": s.parent_span_id, "name": s.name, "component": s.component,
                "start_ms": round(s.start_ms, 3), "duration_ms": round(s.duration_ms, 3), "status": s.status,
                "tokens": s.tokens, "cost": s.cost, "attributes": s.attributes or {}, "error": s.error}

    def _waterfall(self, spans) -> List[Dict[str, Any]]:
        total = max((s.start_ms + s.duration_ms for s in spans), default=1.0) or 1.0
        return [{"name": s.name, "component": s.component, "offset_pct": round(s.start_ms / total * 100, 2),
                 "width_pct": round(s.duration_ms / total * 100, 2), "duration_ms": round(s.duration_ms, 3),
                 "status": s.status, "depth": self._depth(s, spans)} for s in spans]

    @staticmethod
    def _depth(span, spans) -> int:
        by_id = {s.id: s for s in spans}
        depth, cur = 0, span
        while cur.parent_span_id and cur.parent_span_id in by_id and depth < 10:
            depth += 1; cur = by_id[cur.parent_span_id]
        return depth

    @staticmethod
    def _rule_row(r) -> Dict[str, Any]:
        if isinstance(r, dict):
            return r
        return {"id": r.id, "name": r.name, "metric": r.metric, "comparator": r.comparator,
                "threshold": r.threshold, "severity": r.severity, "enabled": r.enabled}
