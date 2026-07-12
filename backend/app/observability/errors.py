"""Observability domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class ObservabilityError(Exception):
    status_code = 400
    code = "observability_error"


class TraceNotFound(ObservabilityError):
    status_code = 404
    code = "trace_not_found"

    def __init__(self, trace_id: str):
        super().__init__(f"Trace '{trace_id}' was not found.")


class RuleNotFound(ObservabilityError):
    status_code = 404
    code = "rule_not_found"

    def __init__(self, rule_id: str):
        super().__init__(f"Alert rule '{rule_id}' was not found.")
