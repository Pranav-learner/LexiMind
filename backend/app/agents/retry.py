"""Retry engine (Step 6) — bounded, deterministic retry for tool execution.

Kept tiny + pure (no sleeping in the sync path so tests stay fast). A tool call is retried up to
`node.retries` attempts; only transient failures (a tool that returned `ok=False` or raised) are
retried — a permission denial is terminal. The executor owns timeouts + cancellation; this owns the
"try again" decision so the policy is one place and easy to evolve (e.g. backoff, jitter later).
"""

from __future__ import annotations

from typing import Callable

from app.agents.interfaces import ToolResult


def run_with_retries(fn: Callable[[], ToolResult], *, max_attempts: int) -> ToolResult:
    attempts = 0
    last: ToolResult | None = None
    for attempts in range(1, max(1, max_attempts) + 1):
        res = fn()
        res.retries = attempts - 1
        if res.ok:
            return res
        last = res
    # exhausted — return the last failed result with the attempt count
    if last is not None:
        last.retries = attempts - 1
    return last  # type: ignore[return-value]
