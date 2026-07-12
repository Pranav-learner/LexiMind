"""Tool base — a tiny helper so concrete tools only declare a spec + an `execute` body.

Concrete tools contain NO business logic: each delegates to an existing LexiMind service and shapes
its output into a uniform `ToolResult`. `safe_execute` (used by the executor) wraps timing + error
capture so a failing tool degrades to `ok=False` rather than throwing through the runtime.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from app.agents.interfaces import ToolResult, ToolSpec


class BaseTool:
    spec: ToolSpec

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:  # pragma: no cover - overridden
        raise NotImplementedError

    # helper for concrete tools
    def _result(self, *, output: Dict[str, Any] | None = None, context_text: str = "",
                citations=None) -> ToolResult:
        return ToolResult(tool=self.spec.name, ok=True, output=output or {},
                          context_text=context_text, citations=citations or [])


def run_tool(tool, ctx, args: Dict[str, Any]) -> ToolResult:
    """Execute a tool, capturing latency + errors into the ToolResult (never raises)."""
    started = time.perf_counter()
    try:
        res = tool.execute(ctx, args)
    except Exception as e:  # a tool failure is data, not a crash
        res = ToolResult(tool=getattr(tool.spec, "name", "unknown"), ok=False, error=str(e)[:2000])
    res.latency_ms = (time.perf_counter() - started) * 1000
    return res
