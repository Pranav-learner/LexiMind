"""Tool Execution Engine (Step 6) — runs an ExecutionGraph safely, layer by layer.

Per node: validate → permission check → execute (with retry + timeout guard) → capture structured
result → advance status. The graph is executed in dependency LAYERS (`graph.layers()`), so the
parallel STRUCTURE of a plan is preserved and reported (each layer is an independently-parallelizable
group shown in the debug timeline).

Execution within a layer is SEQUENTIAL on the request-scoped DB session, because the project's SQLite
`Session` is not thread-safe (same constraint the retrieval orchestrators note). True thread-parallel
tool execution is the ASYNC-READY seam: pass `ctx.services["session_factory"]` and parallel_safe nodes
run on a session-per-tool threadpool. Absent a factory (the default + all tests), the layer runs
sequentially and deterministically. The executor NEVER contains tool business logic — only orchestration;
failures degrade to a `failed`/`denied` node per the node's `on_failure` policy.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Dict, List

from app.agents.graph import ExecutionGraph, GraphNode
from app.agents.interfaces import ToolResult
from app.agents.retry import run_with_retries
from app.agents.tools.base import run_tool


class ToolExecutor:
    def __init__(self, registry, permissions, *, max_parallel: int = 4):
        self.registry = registry
        self.permissions = permissions
        self.max_parallel = max_parallel

    def run_graph(self, graph: ExecutionGraph, ctx, events=None) -> Dict[str, ToolResult]:
        results: Dict[str, ToolResult] = {}
        aborted = False
        session_factory = getattr(ctx, "services", {}).get("session_factory")

        for layer in graph.layers():
            if aborted or getattr(ctx, "_cancelled", False):
                for n in layer:
                    if n.status == "pending":
                        n.status = "cancelled"
                continue

            runnable = [n for n in layer if self._should_run(n, results)]
            for n in layer:
                if n not in runnable and n.status == "pending":
                    n.status = "skipped"

            par = [n for n in runnable if self.registry.spec(n.tool).parallel_safe and n.mode == "parallel"]
            if session_factory is not None and len(par) > 1:
                # Async-ready path: each parallel tool gets its OWN session (thread-safe).
                self._run_parallel(par, ctx, results, events, session_factory)
                runnable = [n for n in runnable if n not in par]

            # Everything else (and, by default, ALL nodes) runs sequentially on the shared session.
            for n in runnable:
                results[n.id] = self._run_node(n, ctx, results, events)

            for n in layer:
                if n.status == "failed" and n.on_failure == "abort":
                    aborted = True
        return results

    # ------------------------------------------------------------------ parallel (opt-in, session-per-tool)
    def _run_parallel(self, nodes: List[GraphNode], ctx, results, events, session_factory) -> None:
        import copy

        def _run_isolated(node: GraphNode) -> ToolResult:
            db = session_factory()
            iso = copy.copy(ctx)
            iso.db = db
            try:
                return self._run_node(node, iso, results, events)
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(nodes)), thread_name_prefix="tool") as pool:
            for node, res in zip(nodes, pool.map(_run_isolated, nodes)):
                results[node.id] = res

    # ------------------------------------------------------------------ per-node
    def _run_node(self, node: GraphNode, ctx, results: Dict[str, ToolResult], events) -> ToolResult:
        spec = self.registry.spec(node.tool)
        ok, reason = self.permissions.allows(spec, ctx)
        if not ok:
            node.status = "denied"; node.error = reason
            if events:
                events.emit("tool_denied", {"node": node.id, "tool": node.tool, "reason": reason})
            return ToolResult(tool=node.tool, ok=False, error=f"permission denied: {reason}")

        tool = self.registry.get(node.tool)
        node.status = "running"
        if events:
            events.emit("tool_start", {"node": node.id, "tool": node.tool})
        started = time.perf_counter()

        def _call() -> ToolResult:
            return _with_timeout(lambda: run_tool(tool, ctx, node.args), spec.timeout_s, node.tool)

        res = run_with_retries(_call, max_attempts=max(1, node.retries))
        node.latency_ms = (time.perf_counter() - started) * 1000
        node.attempts = res.retries + 1
        node.status = "ok" if res.ok else "failed"
        node.error = res.error if not res.ok else None
        node.result_preview = (res.context_text or str(res.output))[:280]
        if events:
            events.emit("tool_end", {"node": node.id, "tool": node.tool, "ok": res.ok,
                                     "latency_ms": round(node.latency_ms, 3), "attempts": node.attempts})
        return res

    @staticmethod
    def _should_run(node: GraphNode, results: Dict[str, ToolResult]) -> bool:
        """Conditional nodes: `has_results:<node_id>` runs only if that node returned non-empty output."""
        if not node.condition:
            return True
        try:
            kind, ref = node.condition.split(":", 1)
        except ValueError:
            return True
        if kind == "has_results":
            r = results.get(ref)
            return bool(r and r.ok and (r.citations or r.context_text or r.output))
        return True


def _with_timeout(fn, timeout_s: float, tool_name: str) -> ToolResult:
    """Guard a tool call with a wall-clock timeout using a single-worker pool (sync-friendly)."""
    with ThreadPoolExecutor(max_workers=1) as p:
        fut = p.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FutureTimeout:
            return ToolResult(tool=tool_name, ok=False, error=f"tool timed out after {timeout_s}s")
