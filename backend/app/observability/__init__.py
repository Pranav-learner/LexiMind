"""AI Observability & Monitoring Platform (Phase 8, Module 2) — OpenTelemetry-native, built-in.

End-to-end visibility over every AI request WITHOUT another logging system: it UNIFIES the telemetry each
module already writes (RetrievalLog / AgentExecutionLog / VerificationLog / EvaluationRunLog / …) into one
normalized feed + metrics + cost/token accounting + health, and adds cross-cutting DISTRIBUTED TRACES
(parent-child spans) the siloed logs can't express. A Telemetry Bus is the single publish point (OTLP/
Langfuse/Phoenix exporters are drop-in sinks). Instrumentation WRAPS the production pipeline — it never
duplicates it.

    interfaces.py   SpanRecord/TraceRecord/TelemetryEvent + TelemetrySink/TelemetrySource protocols
    models.py       Trace/Span (distributed tracing) + AlertRule/AlertEvent
    bus.py          TelemetryBus (in-memory + OTel-ready exporter sink)
    tracer.py       Tracer + nested span context managers (batched async-style flush)
    instrument.py   traced_query — distributed tracing wrapping the real retrieval→answer→verify pipeline
    unifier.py      TelemetryUnifier — normalized VIEW over existing log tables (consume, don't duplicate)
    metrics.py      MetricsCollector (counters/histograms/timers/gauges)
    cost.py         CostTracker (token + cost accounting per source/operation)
    health.py       HealthMonitor
    alerts.py       AlertEngine (configurable threshold rules)
    repository/service/schemas/api  data access + orchestration + DTOs + routes
"""
