"""Agent Scheduler (Step 4) + Failure Recovery (Step 9) — execute a TaskGraph safely.

Runs the graph in dependency LAYERS (`TaskGraph.layers()`), so independent nodes form a parallelizable
group (priority-ordered within the layer). Per node: dependency check → run with retry → timeout guard →
fallback agent → structured outcome. Policy:

- dependency resolution — a node runs only if every dependency finished OK/RECOVERED; otherwise it is
  SKIPPED (graceful degradation — a failed branch never crashes the run).
- retry / timeout       — up to `node.retries` attempts, each guarded by `node.timeout_s`.
- fallback              — if a node still fails and declares a `fallback` agent, try it once → RECOVERED.
- optional              — an optional node's failure never aborts the workflow.
- cancellation          — a cancel flag is checked between layers.
- parallel (opt-in)     — when `parallel=True` (a session factory is available), a layer's nodes run on a
                          threadpool (session-per-node); otherwise the layer runs sequentially on the
                          shared session (deterministic default — the SQLite session isn't thread-safe).

The scheduler owns NO agent logic — `run_node(node)` (injected by the orchestrator) does the dispatch.
It returns orchestration telemetry (order / parallel width / completed / failed / skipped / recovered).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Dict, List, Optional

from app.orchestration.interfaces import (
    CANCELLED, FAILED, OK, PENDING, RECOVERED, RUNNING, SKIPPED, TaskGraph, TaskNode,
)


class AgentScheduler:
    def __init__(self, *, max_parallel: int = 4):
        self.max_parallel = max_parallel

    def run(self, graph: TaskGraph, *, run_node: Callable[[TaskNode], Dict[str, Any]], bus,
            cancel_flag: Optional[Callable[[], bool]] = None, parallel: bool = False) -> Dict[str, Any]:
        order: List[str] = []
        retries_total = 0
        aborted = False

        for layer in graph.layers():
            if aborted or (cancel_flag and cancel_flag()):
                for n in layer:
                    if n.status == PENDING:
                        n.status = CANCELLED
                continue

            # gate: skip nodes whose required dependencies did not succeed (cascade / graceful degradation)
            runnable: List[TaskNode] = []
            for n in layer:
                unmet = [d for d in n.depends_on
                         if (graph.by_id(d) is None or graph.by_id(d).status not in (OK, RECOVERED))]
                if unmet:
                    n.status = SKIPPED
                    n.error = f"dependency not satisfied: {', '.join(unmet)}"
                    bus.status(n.id, SKIPPED, n.error)
                else:
                    runnable.append(n)

            if parallel and len(runnable) > 1:
                self._run_layer_parallel(runnable, run_node, bus, order)
            else:
                for n in runnable:
                    self._run_one(n, run_node, bus, order)

            retries_total += sum(max(0, n.attempts - 1) for n in layer)
            # a REQUIRED node that ultimately failed aborts scheduling of further dependent layers only
            # via the dependency gate above — we never hard-abort the whole run for graceful degradation.

        return {
            "order": order,
            "parallel_tasks": graph.max_width(),
            "completed": sum(1 for n in graph.nodes if n.status in (OK, RECOVERED)),
            "failed": sum(1 for n in graph.nodes if n.status == FAILED),
            "skipped": sum(1 for n in graph.nodes if n.status == SKIPPED),
            "recovered": sum(1 for n in graph.nodes if n.status == RECOVERED),
            "cancelled": sum(1 for n in graph.nodes if n.status == CANCELLED),
            "retries": retries_total,
        }

    # ------------------------------------------------------------------ per-node execution + recovery
    def _run_one(self, node: TaskNode, run_node, bus, order: List[str]) -> None:
        order.append(node.id)
        node.status = RUNNING
        bus.task_request(node.id, node.agent, node.objective or "")
        started = time.perf_counter()

        outcome = self._attempt(node, node.agent, run_node)
        # retries are handled inside _attempt; try a fallback agent if still failing
        if not outcome.get("ok") and node.fallback:
            bus.error(node.id, outcome.get("error") or "failed", recovered=False)
            fb = self._attempt(node, node.fallback, run_node)
            if fb.get("ok"):
                node.status = RECOVERED
                node.recovered_by = node.fallback
                outcome = fb
                bus.status(node.id, RECOVERED, f"recovered via {node.fallback}")
        node.latency_ms = (time.perf_counter() - started) * 1000

        if outcome.get("ok"):
            if node.status != RECOVERED:
                node.status = OK
            node.task_id = outcome.get("task_id")
            node.result_summary = (outcome.get("summary") or "")[:280]
            bus.result(node.id, node.agent, task_id=node.task_id or "", summary=node.result_summary,
                       evidence=outcome.get("evidence", 0), confidence=outcome.get("confidence"))
        else:
            node.status = SKIPPED if node.optional else FAILED
            node.error = outcome.get("error")
            bus.error(node.id, node.error or "failed", recovered=False)
            bus.status(node.id, node.status, "optional — continuing" if node.optional else "required failure")

    def _attempt(self, node: TaskNode, agent: str, run_node) -> Dict[str, Any]:
        last: Dict[str, Any] = {"ok": False, "error": "not run"}
        for _ in range(max(1, node.retries)):
            node.attempts += 1
            try:
                last = _with_timeout(lambda: run_node(node, agent), node.timeout_s)
            except Exception as e:  # a node crash is data, not a scheduler crash
                last = {"ok": False, "error": str(e)[:500]}
            if last.get("ok"):
                return last
        return last

    def _run_layer_parallel(self, nodes: List[TaskNode], run_node, bus, order: List[str]) -> None:
        # each node runs on its own thread; `run_node` is expected to isolate its DB session per call.
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(nodes)),
                                thread_name_prefix="orch") as pool:
            list(pool.map(lambda n: self._run_one(n, run_node, bus, order), nodes))


def _with_timeout(fn, timeout_s: float) -> Dict[str, Any]:
    """Guard a node run with a wall-clock timeout (single-worker pool — mirrors the Module-1 executor)."""
    with ThreadPoolExecutor(max_workers=1) as p:
        fut = p.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FutureTimeout:
            return {"ok": False, "error": f"node timed out after {timeout_s}s"}
