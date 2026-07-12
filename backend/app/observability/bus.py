"""Telemetry Bus (Step 11) — the single publish point every trace flows through.

Modules never create their own logging system: they emit spans/traces which the Tracer both PERSISTS
(DB) and PUBLISHES to this bus. The bus fans a `TraceRecord` out to registered `TelemetrySink`s — an
in-memory ring buffer (live tail / tests) today, and pluggable OTLP / Langfuse / Phoenix exporters later
(the `TelemetrySink` protocol is the seam). Publishing is best-effort + non-blocking (a sink error never
affects the request).
"""

from __future__ import annotations

from collections import deque
from typing import List, Optional

from app.observability.interfaces import TraceRecord


class InMemorySink:
    """A bounded ring buffer of recent traces — live tail for the dashboard + a test sink."""
    name = "in-memory"

    def __init__(self, capacity: int = 500):
        self._buf: "deque[TraceRecord]" = deque(maxlen=capacity)

    def export(self, trace: TraceRecord) -> None:
        self._buf.append(trace)

    def recent(self, limit: int = 50) -> List[TraceRecord]:
        return list(self._buf)[-limit:][::-1]


class OtelExporterSink:
    """OpenTelemetry-ready seam (Step 15). No-op until an OTLP endpoint is configured; wiring a real
    exporter here needs no change anywhere else."""
    name = "otel"

    def __init__(self, exporter=None):
        self._exporter = exporter

    def export(self, trace: TraceRecord) -> None:  # pragma: no cover - exporter is optional
        if self._exporter is not None:
            try:
                self._exporter.export(trace)
            except Exception:
                pass


class TelemetryBus:
    def __init__(self):
        self.memory = InMemorySink()
        self._sinks = [self.memory, OtelExporterSink()]

    def register_sink(self, sink) -> None:
        self._sinks.append(sink)

    def publish(self, trace: TraceRecord) -> None:
        for sink in self._sinks:
            try:
                sink.export(trace)
            except Exception:
                continue   # a sink failure never breaks the request


_BUS: Optional[TelemetryBus] = None


def bus() -> TelemetryBus:
    global _BUS
    if _BUS is None:
        _BUS = TelemetryBus()
    return _BUS
