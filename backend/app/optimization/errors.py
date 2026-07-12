"""Optimization domain errors (transport-agnostic; each carries a `status_code`)."""

from __future__ import annotations


class OptimizationError(Exception):
    status_code = 400
    code = "optimization_error"


class UnknownPolicy(OptimizationError):
    status_code = 422
    code = "unknown_policy"

    def __init__(self, name: str, allowed):
        super().__init__(f"Unknown policy '{name}'. Allowed: {', '.join(allowed)}.")
