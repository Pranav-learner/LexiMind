"""Distributed Tracer (Steps 3 & 4) — nested spans with parent-child relationships.

Usage (instrumentation wraps the real pipeline — it does not duplicate it):

    tracer = Tracer(db, workspace_id, owner_id)
    with tracer.trace("query") as tr:
        with tr.span("retrieval", component="retrieval") as s:
            ... ; s.add_tokens(120); s.set_attribute("results", 8)
        with tr.span("answer", component="answer_service") as s:
            ...

Spans time themselves; `start_ms` is the offset from the trace start (a waterfall). On trace exit the
whole trace + its spans are flushed to the DB in ONE batched commit and published to the TelemetryBus —
so instrumentation adds a per-span `perf_counter` read on the hot path and a single async-style write at
the end (Step 13). A span exception marks the span (and trace) `error` without raising through the app.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

from app.observability.bus import bus as global_bus
from app.observability.interfaces import SpanRecord, TraceRecord


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class SpanHandle:
    def __init__(self, record: SpanRecord):
        self._r = record

    def set_attribute(self, key: str, value: Any) -> "SpanHandle":
        self._r.attributes[key] = value; return self

    def add_tokens(self, n: int) -> "SpanHandle":
        self._r.tokens += int(n or 0); return self

    def set_cost(self, cost: float) -> "SpanHandle":
        self._r.cost += float(cost or 0.0); return self

    def set_error(self, error: str) -> "SpanHandle":
        self._r.status = "error"; self._r.error = str(error)[:1000]; return self


class TraceContext:
    def __init__(self, record: TraceRecord):
        self.record = record
        self._t0 = time.perf_counter()
        self._stack: list = []

    @contextmanager
    def span(self, name: str, *, component: str = "", **attributes):
        rec = SpanRecord(id=_sid("spn"), trace_id=self.record.id, name=name, component=component,
                         parent_span_id=(self._stack[-1] if self._stack else None),
                         start_ms=(time.perf_counter() - self._t0) * 1000, attributes=dict(attributes))
        self._stack.append(rec.id)
        started = time.perf_counter()
        handle = SpanHandle(rec)
        try:
            yield handle
        except Exception as e:      # capture the failure as span data, then re-raise for the app to handle
            rec.status = "error"; rec.error = str(e)[:1000]
            self.record.status = "error"
            raise
        finally:
            rec.duration_ms = (time.perf_counter() - started) * 1000
            self.record.spans.append(rec)
            self.record.token_usage += rec.tokens
            self.record.cost_estimate += rec.cost
            self._stack.pop()

    def set_attribute(self, key: str, value: Any) -> None:
        self.record.attributes[key] = value


class Tracer:
    def __init__(self, db, workspace_id: str, owner_id: str, *, bus=None, persist: bool = True):
        self.db = db
        self.workspace_id = workspace_id
        self.owner_id = owner_id
        self.bus = bus or global_bus()
        self.persist = persist

    @contextmanager
    def trace(self, operation: str = "request", **attributes):
        record = TraceRecord(id=_sid("trc"), workspace_id=self.workspace_id, owner_id=self.owner_id,
                             operation=operation, attributes=dict(attributes))
        ctx = TraceContext(record)
        t0 = time.perf_counter()
        try:
            yield ctx
        except Exception as e:
            record.status = "error"; record.error = str(e)[:1000]
            raise
        finally:
            record.total_ms = (time.perf_counter() - t0) * 1000
            self._flush(record)

    def _flush(self, record: TraceRecord) -> None:
        # persist (batched: one Trace + N Spans) then publish to the bus (in-memory + exporters)
        if self.persist:
            try:
                from app.observability.repository import ObservabilityRepository
                ObservabilityRepository(self.db).save_trace(record)
            except Exception:
                try:
                    self.db.rollback()
                except Exception:
                    pass
        try:
            self.bus.publish(record)
        except Exception:
            pass
