"""Agent Runtime (Step 3) — the central orchestration layer above Retrieval + Context.

Flow (the runtime owns NO per-tool business logic):

    request → AgentContext → Planner.plan → permission-gated ToolExecutor.run_graph
            → collect tool evidence into memory → PromptPackage → answer_service.complete → persist log

The runtime is the ONLY place the phases compose: it reuses the existing retrieval/context/generation
services (through tools) and the single `AnswerService` inference pathway (through `ctx.answer_fn()`).
It is interface-driven — planner, permissions, executor, memory, and event sink are all injectable, so
future modules replace any piece without touching this file.

`run()` is synchronous (request-scoped) with async-ready seams (parallel executor, event sink). It
returns a rich result (answer + serialized graph + tool results + timeline + timings) AND the
`AgentExecutionLog` telemetry row.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.agents.context import AgentContext, AgentState
from app.agents.events import InMemoryEventSink
from app.agents.executor import ToolExecutor
from app.agents.memory import MemoryManager
from app.agents.permissions import PermissionManager
from app.agents.planner import HeuristicPlanner
from app.agents.prompt_package import PromptPackage
from app.agents.registry import tool_registry


def _estimate_tokens(text: str) -> int:
    # cheap heuristic (chars/4), reused for the cost estimate — no tokenizer dependency
    return max(0, len(text) // 4)


class AgentRuntime:
    def __init__(self, *, planner=None, executor=None, registry=None):
        self.registry = registry or tool_registry()
        self.planner = planner or HeuristicPlanner()
        self.executor = executor  # built per-run with the run's permission manager

    def run(self, ctx: AgentContext, *, permissions: Optional[PermissionManager] = None) -> Dict[str, Any]:
        state = AgentState()
        events = InMemoryEventSink()
        ctx.memory = ctx.memory or MemoryManager()
        ctx.events = events
        permissions = permissions or PermissionManager(ctx.granted_permissions or None,
                                                       allowed_tools=ctx.allowed_tools)
        executor = self.executor or ToolExecutor(self.registry, permissions)
        started = time.perf_counter()

        # 1) plan
        state.phase = "planning"
        t = time.perf_counter()
        plan = self.planner.plan(ctx)
        state.planner_ms = (time.perf_counter() - t) * 1000
        events.emit("plan", {"planner": plan.planner, "requires_tools": plan.requires_tools,
                             "nodes": [n.tool for n in plan.graph.nodes], "rationale": plan.rationale})

        # 2) execute tools (permission-gated inside the executor)
        state.phase = "executing"
        t = time.perf_counter()
        tool_results: Dict[str, Any] = {}
        if plan.requires_tools:
            tool_results = executor.run_graph(plan.graph, ctx, events)
        state.tools_ms = (time.perf_counter() - t) * 1000
        state.tool_count = len(tool_results)
        state.retry_count = sum(n.attempts - 1 for n in plan.graph.nodes if n.attempts > 0)

        # 3) collect evidence → PromptPackage
        state.phase = "synthesizing"
        pkg = PromptPackage(query=ctx.query)
        for node in plan.graph.nodes:
            res = tool_results.get(node.id)
            if res is not None and res.ok:
                ctx.memory.record_tool(node.id, res)
                pkg.add_tool_evidence(node.tool, res)

        # 4) single LLM pathway — build prompt package → answer_service.complete (injected)
        prompt = pkg.render()
        t = time.perf_counter()
        try:
            answer = (ctx.answer_fn()(prompt) or "").strip()
            state.llm_ms = (time.perf_counter() - t) * 1000
        except Exception as e:  # keep the run observable even if inference fails
            state.llm_ms = (time.perf_counter() - t) * 1000
            state.phase = "failed"; state.error = f"answer service failed: {e}"
            answer = ""

        state.total_ms = (time.perf_counter() - started) * 1000
        if state.phase != "failed":
            state.phase = "done"
        events.emit("done", {"answer_chars": len(answer), "total_ms": round(state.total_ms, 3)})

        token_usage = _estimate_tokens(prompt) + _estimate_tokens(answer)
        return {
            "execution_id": ctx.execution_id, "agent": ctx.agent, "answer": answer,
            "success": state.phase == "done", "phase": state.phase, "error": state.error,
            "plan": plan.to_dict(),
            "citations": pkg.citations,
            "prompt_package": pkg.to_dict(),
            "tool_results": [{"node": nid, **r.to_dict()} for nid, r in tool_results.items()],
            "timeline": events.timeline(),
            "timings": {"planner_ms": round(state.planner_ms, 3), "tools_ms": round(state.tools_ms, 3),
                        "llm_ms": round(state.llm_ms, 3), "total_ms": round(state.total_ms, 3)},
            "retry_count": state.retry_count, "tool_count": state.tool_count,
            "token_usage": token_usage, "estimated_cost": plan.estimated_cost,
            "memory": ctx.memory.snapshot(),
        }
