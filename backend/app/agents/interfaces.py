"""Agent framework interfaces — the interface-driven core (Phase 6, Module 1).

Everything in the framework is programmed against these small Protocols + value objects so future
modules (advanced planners, new tools, multi-agent orchestration, external tool ecosystems) drop in
WITHOUT touching the runtime. The runtime depends on abstractions, never on concrete tools.

Value objects (dataclasses):
- `ToolSpec`   — a tool's static contract (name/version/params/permissions/metadata). Powers discovery,
                 validation, and permission checks WITHOUT importing the tool.
- `ToolResult` — the structured, uniform output every tool returns (ok/output/context_text/citations/
                 telemetry). The runtime only ever sees this shape.

Protocols (structural typing — no inheritance required):
- `Tool`             — `spec` + `execute(ctx, args) -> ToolResult`. The ONLY business-logic seam;
                       concrete tools delegate to existing services and add no logic of their own.
- `Planner`          — `plan(ctx) -> ExecutionPlan`. Replaceable (heuristic now, LLM-reasoning later).
- `PermissionPolicy` — `allows(spec, ctx) -> (bool, reason)`. The runtime never runs a denied tool.
- `MemoryStore`      — the working/execution/scratchpad memory seam (in-memory now, semantic later).
- `EventSink`        — `emit(event)`. Observability/streaming seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

if TYPE_CHECKING:  # avoid import cycles — these are only annotations
    from app.agents.context import AgentContext
    from app.agents.graph import ExecutionPlan


# --------------------------------------------------------------------- value objects
@dataclass
class ToolParam:
    name: str
    type: str = "string"            # string | integer | boolean | object
    required: bool = False
    description: str = ""


@dataclass
class ToolSpec:
    name: str
    version: str = "1.0"
    description: str = ""
    category: str = "general"        # search | retrieval | generation | analytics | write
    params: List[ToolParam] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)   # e.g. ["search"], ["generate","write"]
    parallel_safe: bool = True        # may run concurrently with other parallel_safe tools
    timeout_s: float = 30.0
    cost_weight: float = 1.0          # relative cost estimate (for planner budgeting)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version, "description": self.description,
                "category": self.category, "permissions": self.permissions,
                "parallel_safe": self.parallel_safe, "timeout_s": self.timeout_s,
                "cost_weight": self.cost_weight,
                "params": [{"name": p.name, "type": p.type, "required": p.required,
                            "description": p.description} for p in self.params]}


@dataclass
class ToolResult:
    tool: str
    ok: bool = True
    output: Dict[str, Any] = field(default_factory=dict)   # structured machine-readable result
    context_text: str = ""                                  # text this tool contributes to the prompt
    citations: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0
    cached: bool = False

    def to_dict(self, *, preview: int = 600) -> Dict[str, Any]:
        return {"tool": self.tool, "ok": self.ok,
                "output": self.output, "context_preview": (self.context_text or "")[:preview],
                "citation_count": len(self.citations), "error": self.error,
                "latency_ms": round(self.latency_ms, 3), "retries": self.retries, "cached": self.cached}


# --------------------------------------------------------------------- protocols
@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec
    def execute(self, ctx: "AgentContext", args: Dict[str, Any]) -> ToolResult: ...


class Planner(Protocol):
    name: str
    def plan(self, ctx: "AgentContext") -> "ExecutionPlan": ...


class PermissionPolicy(Protocol):
    def allows(self, spec: ToolSpec, ctx: "AgentContext") -> Tuple[bool, str]: ...


class MemoryStore(Protocol):
    def put(self, scope: str, key: str, value: Any) -> None: ...
    def get(self, scope: str, key: str, default: Any = None) -> Any: ...
    def scope(self, scope: str) -> Dict[str, Any]: ...


class EventSink(Protocol):
    def emit(self, event: str, payload: Dict[str, Any]) -> None: ...
