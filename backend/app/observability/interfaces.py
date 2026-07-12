"""Observability interfaces (Phase 8, Module 2) — the interface-driven, OTel-ready core.

Value objects mirror the OpenTelemetry data model (Trace → Spans → attributes) so a future OTLP/Langfuse/
Phoenix exporter is a drop-in `TelemetrySink` — the internal architecture never changes (Step 15).

- `SpanRecord`  — one unit of work (name/component/timing/status/tokens/cost/attributes) + parent link.
- `TraceRecord` — a request's root trace + its spans.
- `TelemetryEvent` — a normalized event from ANY source (a trace OR a unified existing log row).

Protocols:
- `TelemetrySink` — `export(trace)` — where traces go (DB now; OTLP/Langfuse/Phoenix later).
- `TelemetrySource` — `events(db, workspace, owner, limit)` — a normalized view over an EXISTING log table
                      (the "consume existing telemetry, don't duplicate" seam).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class SpanRecord:
    id: str
    trace_id: str
    name: str
    component: str = ""
    parent_span_id: Optional[str] = None
    start_ms: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"
    tokens: int = 0
    cost: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "trace_id": self.trace_id, "parent_span_id": self.parent_span_id,
                "name": self.name, "component": self.component, "start_ms": round(self.start_ms, 3),
                "duration_ms": round(self.duration_ms, 3), "status": self.status, "tokens": self.tokens,
                "cost": round(self.cost, 6), "attributes": self.attributes, "error": self.error}


@dataclass
class TraceRecord:
    id: str
    workspace_id: str
    owner_id: str
    operation: str = "request"
    status: str = "ok"
    total_ms: float = 0.0
    token_usage: int = 0
    cost_estimate: float = 0.0
    error: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    spans: List[SpanRecord] = field(default_factory=list)

    def to_dict(self, *, include_spans: bool = True) -> Dict[str, Any]:
        d = {"id": self.id, "workspace_id": self.workspace_id, "operation": self.operation,
             "status": self.status, "total_ms": round(self.total_ms, 3), "span_count": len(self.spans),
             "token_usage": self.token_usage, "cost_estimate": round(self.cost_estimate, 6),
             "error": self.error, "attributes": self.attributes}
        if include_spans:
            d["spans"] = [s.to_dict() for s in self.spans]
        return d


@dataclass
class TelemetryEvent:
    source: str                 # trace | retrieval | agent_run | verification | evaluation | …
    id: str
    workspace_id: str
    operation: str = ""
    latency_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    status: str = "completed"
    created_at: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "id": self.id, "workspace_id": self.workspace_id,
                "operation": self.operation, "latency_ms": round(self.latency_ms, 3), "tokens": self.tokens,
                "cost": round(self.cost, 6), "status": self.status, "created_at": self.created_at,
                "detail": self.detail}


# --------------------------------------------------------------------- protocols
class TelemetrySink(Protocol):
    name: str
    def export(self, trace: TraceRecord) -> None: ...


class TelemetrySource(Protocol):
    source: str
    def events(self, db, workspace_id: str, owner_id: str, *, limit: int) -> List[TelemetryEvent]: ...
