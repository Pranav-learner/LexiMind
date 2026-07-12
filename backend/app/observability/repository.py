"""Data access for observability — traces/spans (batched writes) + alert rules/events."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.observability.interfaces import TraceRecord
from app.observability.models import AlertEvent, AlertRule, Span, Trace


class ObservabilityRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ traces / spans (batched)
    def save_trace(self, record: TraceRecord) -> Trace:
        trace = Trace(id=record.id, workspace_id=record.workspace_id, owner_id=record.owner_id,
                      operation=record.operation, status=record.status, total_ms=record.total_ms,
                      span_count=len(record.spans), token_usage=record.token_usage,
                      cost_estimate=record.cost_estimate, error=record.error, attributes=record.attributes or None)
        self.db.add(trace)
        for s in record.spans:
            self.db.add(Span(id=s.id, trace_id=record.id, parent_span_id=s.parent_span_id,
                             workspace_id=record.workspace_id, name=s.name, component=s.component,
                             start_ms=s.start_ms, duration_ms=s.duration_ms, status=s.status, tokens=s.tokens,
                             cost=s.cost, attributes=s.attributes or None, error=s.error))
        self.db.commit()   # ONE commit for the whole trace
        return trace

    def get_trace(self, trace_id: str, owner_id: str) -> Optional[Trace]:
        return self.db.scalar(select(Trace).where(Trace.id == trace_id, Trace.owner_id == owner_id))

    def spans_for(self, trace_id: str) -> List[Span]:
        return list(self.db.scalars(select(Span).where(Span.trace_id == trace_id).order_by(Span.start_ms)))

    def traces(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[Trace]:
        return list(self.db.scalars(select(Trace).where(
            Trace.workspace_id == workspace_id, Trace.owner_id == owner_id)
            .order_by(desc(Trace.created_at)).limit(limit)))

    # ------------------------------------------------------------------ alert rules / events
    def create_rule(self, rule: AlertRule) -> AlertRule:
        self.db.add(rule); self.db.commit(); self.db.refresh(rule); return rule

    def rules(self, workspace_id: str, owner_id: str) -> List[AlertRule]:
        return list(self.db.scalars(select(AlertRule).where(
            AlertRule.workspace_id == workspace_id, AlertRule.owner_id == owner_id)))

    def delete_rule(self, rule_id: str, owner_id: str) -> bool:
        r = self.db.scalar(select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_id == owner_id))
        if r is None:
            return False
        self.db.delete(r); self.db.commit(); return True

    def save_events(self, events: List[AlertEvent]) -> None:
        for e in events:
            self.db.add(e)
        if events:
            self.db.commit()

    def recent_events(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[AlertEvent]:
        return list(self.db.scalars(select(AlertEvent).where(
            AlertEvent.workspace_id == workspace_id, AlertEvent.owner_id == owner_id)
            .order_by(desc(AlertEvent.created_at)).limit(limit)))
