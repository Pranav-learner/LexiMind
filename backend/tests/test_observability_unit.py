"""Unit tests for the Phase-8 Module-2 Observability platform — pure/offline (no HTTP, no LLM).

Covers the distributed tracer (nested spans / parent-child / error capture / token roll-up), the
telemetry bus, the metrics collector, the cost tracker, and the alert engine.
"""

from __future__ import annotations

from app.observability.alerts import AlertEngine, DEFAULT_RULES
from app.observability.bus import TelemetryBus
from app.observability.cost import CostTracker
from app.observability.interfaces import TelemetryEvent
from app.observability.metrics import MetricsCollector, _percentile
from app.observability.tracer import Tracer


# --------------------------------------------------------------------- tracer
def test_tracer_nested_spans_and_parent_child():
    bus = TelemetryBus()
    tracer = Tracer(None, "ws", "o", bus=bus, persist=False)
    with tracer.trace("query") as tr:
        with tr.span("retrieval", component="retrieval") as s:
            s.set_attribute("results", 8); s.add_tokens(100)
            with tr.span("fusion", component="retrieval"):   # nested → child of retrieval
                pass
        with tr.span("answer", component="answer_service") as s:
            s.add_tokens(50)
    rec = bus.memory.recent(1)[0]
    assert len(rec.spans) == 3 and rec.token_usage == 150 and rec.status == "ok"
    fusion = next(s for s in rec.spans if s.name == "fusion")
    retrieval = next(s for s in rec.spans if s.name == "retrieval")
    assert fusion.parent_span_id == retrieval.id            # nested span is a child
    assert retrieval.attributes["results"] == 8


def test_tracer_captures_span_error():
    bus = TelemetryBus()
    tracer = Tracer(None, "ws", "o", bus=bus, persist=False)
    try:
        with tracer.trace("q") as tr:
            with tr.span("boom"):
                raise ValueError("kaboom")
    except ValueError:
        pass
    rec = bus.memory.recent(1)[0]
    assert rec.status == "error" and rec.spans[0].status == "error" and "kaboom" in rec.spans[0].error


# --------------------------------------------------------------------- bus
def test_bus_publishes_to_sinks():
    bus = TelemetryBus()
    seen = []
    bus.register_sink(type("S", (), {"name": "t", "export": lambda self, tr: seen.append(tr.id)})())
    Tracer(None, "ws", "o", bus=bus, persist=False).trace("q").__enter__()  # start+auto-flush
    with Tracer(None, "ws", "o", bus=bus, persist=False).trace("q2"):
        pass
    assert seen                                              # the custom sink received traces


# --------------------------------------------------------------------- metrics
def _ev(source, latency, status="completed", tokens=0, cost=0.0):
    return TelemetryEvent(source=source, id="x", workspace_id="ws", latency_ms=latency, status=status,
                          tokens=tokens, cost=cost)


def test_percentile():
    assert _percentile([10, 20, 30, 40, 50], 50) == 30 and _percentile([], 95) == 0.0


def test_metrics_summary():
    events = [_ev("retrieval", 10), _ev("retrieval", 30), _ev("agent_run", 100, "failed", tokens=500)]
    s = MetricsCollector().summarize(events)
    assert s["requests"] == 3 and s["errors"] == 1 and s["error_rate"] == round(1 / 3, 4)
    assert s["latency_ms"]["p95"] > 0 and s["tokens_total"] == 500
    assert s["by_source"]["agent_run"]["error_rate"] == 1.0
    flat = MetricsCollector().flat_metrics(events)
    assert "p95_latency_ms" in flat and "error_rate" in flat


# --------------------------------------------------------------------- cost
def test_cost_report_breakdown():
    events = [_ev("agent_run", 10, tokens=100, cost=0.01), _ev("agent_run", 20, tokens=200, cost=0.02),
              _ev("evaluation", 5, tokens=50, cost=0.005), _ev("retrieval", 3)]
    r = CostTracker().report(events)
    assert r["total_tokens"] == 350 and round(r["total_cost"], 4) == 0.035
    assert r["by_source"]["agent_run"]["tokens"] == 300 and r["by_source"]["agent_run"]["count"] == 2
    assert r["top_cost_operations"]


# --------------------------------------------------------------------- alerts
def test_alert_engine_gt_lt():
    fired = AlertEngine().evaluate(
        {"error_rate": 0.3, "p95_latency_ms": 100, "min_quality": 0.4},
        [{"name": "err", "metric": "error_rate", "comparator": "gt", "threshold": 0.2, "severity": "critical"},
         {"name": "lat", "metric": "p95_latency_ms", "comparator": "gt", "threshold": 5000},
         {"name": "quality", "metric": "min_quality", "comparator": "lt", "threshold": 0.5}])
    names = {f["rule_name"] for f in fired}
    assert "err" in names and "quality" in names and "lat" not in names   # only threshold-crossers fire


def test_default_rules_present():
    metrics = {"metric": m["metric"] for m in DEFAULT_RULES}   # noqa: F841
    assert any(r["metric"] == "error_rate" for r in DEFAULT_RULES)
    assert AlertEngine().evaluate({"error_rate": 0.9}, list(DEFAULT_RULES))   # high error rate fires
