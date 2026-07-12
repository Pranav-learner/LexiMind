# Phase 8 — Module 2: AI Observability & Monitoring Platform

> **Status:** ✅ Complete · Backend `app/observability/` · Frontend `OperationsWorkspace` · 15 new tests. UNIFIES the telemetry every module already writes (11 existing `*Log` tables) into one feed + metrics + cost + health — zero re-logging — and adds cross-cutting distributed traces (parent-child spans). Telemetry Bus is the single publish point; OTLP/Langfuse/Phoenix exporters are drop-in sinks. Instrumentation WRAPS the production pipeline.

---

## 1. Module Overview

LexiMind had rich per-module telemetry but no way to see one request end-to-end, no unified metrics, no
cost/token accounting across subsystems, no health view, no alerts. This module is the production ops
layer: **OpenTelemetry + Langfuse + Grafana + Phoenix**, built natively into LexiMind.

**Logging vs observability:**

| Logging (before) | Observability (this module) |
|---|---|
| Many siloed `*Log` tables | One unified telemetry feed over all of them |
| "This module took X ms" | "This *request* took X ms; here's the span waterfall" |
| No cross-cutting view | Distributed traces (parent-child spans) per request |
| Cost scattered per module | Token/cost accounting per source/operation/workspace |
| No health/alerts | Health checks + configurable threshold alerts |

This is monitoring, not optimization (Module 3).

---

## 2. Previous Architecture

Every phase wrote its own log table (RetrievalLog, AgentExecutionLog, AgentTaskLog,
OrchestrationExecutionLog, VerificationLog, GraphConstructionLog, GraphReasoningLog, SemanticMemoryLog,
TemporalSearchLog, EvaluationRunLog, …). Each was queryable in isolation, but there was **no single
request trace**, no aggregated metrics, no cost rollup, no health/alerting. Debugging "why was this slow/
expensive?" meant manually correlating rows across ten tables.

---

## 3. New Architecture

```
Request
   ↓
Tracer  ── nested spans (retrieval → graph → context → answer → verification)
   ↓
Trace + Spans (persisted, batched)  ─┐
                                     ├──→  Telemetry Bus  ──→  sinks (in-memory · OTLP/Langfuse/Phoenix)
Existing *Log tables  ── Unifier ────┘        (single publish point)
   ↓
Metrics · Cost · Health · Alerts  ──→  AI Operations Dashboard
```

Every request gets one complete execution trace; every existing log becomes a unified telemetry event.

---

## 4. Observability Pipeline

1. **Tracing** (`tracer.py`) — `Tracer.trace()` + nested `span()` context managers create parent-child
   spans with a latency waterfall + per-span tokens/cost; flushed to DB in ONE batched commit + published.
2. **Unified telemetry** (`unifier.py`) — a normalized VIEW over the 11 existing `*Log` tables + traces
   (source / latency / tokens / cost / status). Adding a module = one spec, not re-logging.
3. **Metrics** (`metrics.py`) — counters (requests), gauges (error rate), histograms/timers (p50/p95/p99),
   per-source breakdown.
4. **Cost/tokens** (`cost.py`) — accounting per source/operation/workspace from the numbers each module
   already recorded.
5. **Health** (`health.py`) — database / pipelines / caches / knowledge-graph / workers / LLM.
6. **Alerts** (`alerts.py`) — built-in + configurable threshold rules → fired `AlertEvent`s.
7. **Dashboards** — the AI Operations Workspace composes all of the above.

---

## 5. Backend Architecture

```
app/observability/
  interfaces.py   SpanRecord/TraceRecord/TelemetryEvent + TelemetrySink/TelemetrySource protocols
  models.py       Trace / Span (distributed tracing) + AlertRule / AlertEvent
  bus.py          TelemetryBus (in-memory ring buffer + OtelExporterSink seam)
  tracer.py       Tracer + nested span context managers (batched flush)
  instrument.py   traced_query — tracing wrapping the real retrieval→answer→verify pipeline
  unifier.py      TelemetryUnifier — normalized view over existing log tables
  metrics.py      MetricsCollector
  cost.py         CostTracker
  health.py       HealthMonitor
  alerts.py       AlertEngine (+ DEFAULT_RULES)
  repository/service/schemas/api  data access + orchestration + DTOs + routes
  errors.py       transport-agnostic errors (status_code)
```

- **Interfaces / DI** — `TelemetrySink` (where traces go) and `TelemetrySource` (a log-table view) are
  Protocols; the OTel exporter is a sink, so a real OTLP/Langfuse/Phoenix exporter drops in with no other
  change (Step 15). The `traced_query` reuses Module-1 `get_agent_services` (single answer function).
- **Reuse / no duplication** — the unifier READS `RetrievalLog`/`AgentExecutionLog`/`VerificationLog`/… ;
  it re-persists nothing. The only new writes are traces (new cross-cutting data the logs can't express)
  and fired alert events.
- **Validation / errors** — Pydantic bounds + a comparator/severity pattern; `TraceNotFound`/`RuleNotFound`
  → 404.
- **Error handling** — a sink failure never breaks a request; a span exception is captured as span data
  then re-raised; trace flush rolls back on error.

---

## 6. Observability Framework

- **Distributed tracing** — Trace → Spans with `parent_span_id`, `start_ms` offset (waterfall), status,
  tokens, cost, attributes — the OpenTelemetry data model.
- **Span hierarchy** — a stack-based context manager nests spans automatically.
- **Metrics** — counters/gauges/histograms/timers over the unified feed.
- **Health checks** — component checks with worst-of overall status.
- **Alerts** — `gt`/`lt` threshold rules (built-in + custom), fired-event persistence, channel-ready.
- **Telemetry adapters** — the `TelemetrySink` seam = OTLP/Prometheus/Grafana/Jaeger/Langfuse/Phoenix/
  OpenInference/Arize/LangSmith exporters, pluggable without internal changes.

---

## 7. AI Integration

- **Every subsystem** already emits telemetry (its `*Log` table); the unifier consumes it — so retrieval,
  context, graph retrieval, graph reasoning, agent runtime, orchestration, verification, and evaluation are
  all observable with **no new instrumentation** in those modules.
- **The traced pipeline** (`instrument.py`) wraps the REAL retrieval → PromptPackage → single AnswerService
  → Verification Engine in spans — no duplicated execution path; the tracer only observes.
- No duplicated instrumentation; the single AnswerService pathway is preserved.

---

## 8. API Documentation

All routes under `/workspaces/{workspace_id}/observability`, authenticated + workspace-scoped.

| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard` | Full ops dashboard (metrics + cost + health + alerts + recent) |
| GET | `/events?source=&limit=` | Unified telemetry feed (all sources or one) |
| GET | `/metrics` | Aggregate metrics (requests, error rate, latency histogram, by-source) |
| GET | `/cost` | Token + cost report (by source/operation) |
| GET | `/health` | Component health summary |
| GET | `/traces` · `/traces/{id}` | Distributed traces + span waterfall |
| POST | `/trace-query` | Run an INSTRUMENTED real query → full trace |
| GET/POST/DELETE | `/alerts/rules` | Configurable alert rules |
| POST | `/alerts/evaluate` · GET `/alerts` | Evaluate rules now / fired-alert history |

**Errors:** 404 workspace/trace/rule, 401/403 unauthenticated, 422 bad rule.

---

## 9. Performance Optimizations

- **Asynchronous-style telemetry** — spans buffer in memory during the request; ONE batched
  `Trace + N Spans` commit at the end (a per-span `perf_counter` read is the only hot-path cost).
- **Consume, don't re-log** — the unifier reads existing tables (bounded per-source limit) instead of
  writing duplicate telemetry, so instrumentation adds no extra write per module.
- **Bounded** — in-memory ring buffer for the live tail; per-source query caps for the feed.
- **Streaming-ready** — the `TelemetrySink` seam supports a websocket/SSE live sink.
- **Retention / large-scale** — the trace tables are indexed by (workspace, created_at); an exporter can
  offload to a TSDB/OTLP backend for millions of traces.

---

## 10. Testing

- **`tests/test_observability_unit.py` (8)** — tracer (nested spans + parent-child + error capture + token
  roll-up), telemetry bus fan-out, metrics (percentiles + error rate + by-source), cost breakdown, alert
  engine (gt/lt + built-in rules).
- **`tests/test_observability_api.py` (7)** — **traced query** producing a full parent-child distributed
  trace (retrieval→context→answer→verification waterfall), trace list/detail + 404, **unified telemetry**
  (trace + agent_task/verification sources — not re-logged) + metrics + cost + health, source filter,
  configurable alert rules + evaluation + history, dashboard, auth.
- **Regression** — 4 new models registered in `init_db` + conftest; `trace-query` reuses the existing
  `get_agent_services` fake. All Phase 1–8 M1 tests continue to pass (full suite green).

---

## 11. File Changes Summary

**New (backend)** — `app/observability/{__init__,interfaces,models,bus,tracer,instrument,unifier,metrics,
cost,health,alerts,repository,service,schemas,api,errors}.py`; `tests/test_observability_unit.py`;
`tests/test_observability_api.py`.

**Modified (backend)** — `app/db/base.py` (register 4 models), `app/main.py` (mount router),
`tests/conftest.py` (register models + mount router).

**New (frontend)** — `src/api/observability.ts`; `src/pages/OperationsWorkspace.tsx`;
`src/styles/observability.css`.

**Modified (frontend)** — `src/App.tsx` (route), `src/pages/WorkspaceDetail.tsx` (hub link).

*(No prior-phase source files were modified — the platform consumes existing telemetry, so the other
modules have zero regression surface.)*

---

## 12. Future Compatibility

- **Module 3 — AI Optimization & Cost Intelligence** — the cost/token/latency metrics + traces are the
  optimization inputs; the metric engine is shared.
- **Module 4 — Continuous Learning & Feedback** — traces + verification signals feed feedback loops.
- **Enterprise monitoring / multi-region / cloud-native / SRE** — the `TelemetrySink` OTel seam exports to
  Grafana/Jaeger/Prometheus/Langfuse; health + alerts are the SRE surface; the trace tables shard by
  workspace for multi-tenant scale.

---

## 13. Lessons Learned

- **Unify, don't re-log.** The single biggest decision: the observability platform READS the 11 existing
  `*Log` tables via a normalized `TelemetrySource` view rather than re-emitting telemetry — so every
  subsystem became observable with zero new instrumentation and zero duplicate writes (the module's core
  mandate).
- **Traces express what logs can't.** Per-module logs are siloed; a distributed trace (parent-child spans
  with a waterfall) is the one thing they cannot represent, so that is the only NEW persistence added.
- **The bus is the OTel seam.** Publishing every trace through one bus with a `TelemetrySink` protocol
  means an OTLP/Langfuse/Phoenix exporter is a drop-in — the internal architecture never changes.
- **Batched, async-style flush keeps the hot path clean.** Spans buffer in memory; one commit at trace end
  — instrumentation adds a `perf_counter` per span and a single write, never per-span DB round-trips.
- **Tradeoffs / limitations.** Only the reference `traced_query` flow is span-instrumented today; other
  flows are observable via the unifier (their `*Log` rows) rather than fine-grained spans — adopting the
  `Tracer` in `run_task`/reasoning is the incremental next step (deferred to protect the existing tests).
  Health checks are best-effort (LLM availability is declared, not probed). Traces persist to SQL now; an
  OTLP/TSDB exporter behind the sink seam is the path to millions of traces. Alert channels (Slack/webhook)
  are declared fields, not yet wired.
```
```
This completes Phase 8 Module 2 — LexiMind now has end-to-end distributed tracing, unified telemetry,
cost accounting, health, and alerting, built natively and OpenTelemetry-ready.
