"""Execution graph (Step 8) — plans as serializable directed workflows.

A plan is a DAG of `GraphNode`s. Each node names a tool + args and declares its dependencies, failure
policy, and retry budget. The executor runs the graph in dependency LAYERS: nodes whose dependencies
are all satisfied and that are `parallel` run concurrently; `sequential` nodes run alone. This models:

- sequential   — a node depends on another (edge).
- parallel     — independent nodes in the same layer.
- conditional  — a node carries a `condition` key evaluated against prior results (skipped if false).
- retry        — per-node `retries` budget (the executor honors it).
- failure branch — `on_failure` ∈ abort | continue | branch(to `failure_next`).
- cancellation — the executor checks a cancel flag between layers.

The graph is fully `to_dict`/`from_dict` serializable so it can be persisted (AgentExecutionLog),
previewed in the debug panel, and — in future — resumed. Loops / dynamic planning / human-approval
nodes are intentionally out of scope here (future), but the shape leaves room for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GraphNode:
    id: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    mode: str = "parallel"                     # parallel | sequential
    depends_on: List[str] = field(default_factory=list)
    on_failure: str = "continue"              # abort | continue | branch
    failure_next: Optional[str] = None         # node id to jump to when on_failure == branch
    condition: Optional[str] = None            # e.g. "has_results:node_a" — skip node if false
    retries: int = 1

    # --- filled in during execution (telemetry, not business data) ---
    status: str = "pending"                    # pending|running|ok|failed|skipped|denied|cancelled
    latency_ms: float = 0.0
    attempts: int = 0
    error: Optional[str] = None
    result_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "tool": self.tool, "args": self.args, "mode": self.mode,
                "depends_on": self.depends_on, "on_failure": self.on_failure,
                "failure_next": self.failure_next, "condition": self.condition, "retries": self.retries,
                "status": self.status, "latency_ms": round(self.latency_ms, 3), "attempts": self.attempts,
                "error": self.error, "result_preview": self.result_preview}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GraphNode":
        return GraphNode(
            id=d["id"], tool=d["tool"], args=d.get("args", {}), mode=d.get("mode", "parallel"),
            depends_on=d.get("depends_on", []), on_failure=d.get("on_failure", "continue"),
            failure_next=d.get("failure_next"), condition=d.get("condition"), retries=d.get("retries", 1),
            status=d.get("status", "pending"), latency_ms=d.get("latency_ms", 0.0),
            attempts=d.get("attempts", 0), error=d.get("error"), result_preview=d.get("result_preview", ""))


@dataclass
class ExecutionGraph:
    nodes: List[GraphNode] = field(default_factory=list)

    def add(self, node: GraphNode) -> GraphNode:
        self.nodes.append(node)
        return node

    def by_id(self, node_id: str) -> Optional[GraphNode]:
        return next((n for n in self.nodes if n.id == node_id), None)

    def layers(self) -> List[List[GraphNode]]:
        """Topologically order nodes into dependency layers (each layer is independently parallelizable).
        Raises on a dependency cycle (defensive — the heuristic planner never builds one)."""
        remaining = {n.id: n for n in self.nodes}
        done: set = set()
        layers: List[List[GraphNode]] = []
        while remaining:
            ready = [n for n in remaining.values() if all(dep in done for dep in n.depends_on)]
            if not ready:
                raise ValueError("Execution graph has a dependency cycle or missing dependency.")
            layers.append(ready)
            for n in ready:
                done.add(n.id)
                del remaining[n.id]
        return layers

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes]}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ExecutionGraph":
        return ExecutionGraph(nodes=[GraphNode.from_dict(n) for n in (d or {}).get("nodes", [])])


@dataclass
class ExecutionPlan:
    query: str
    requires_tools: bool
    graph: ExecutionGraph
    rationale: str = ""
    planner: str = "heuristic-v1"
    estimated_cost: float = 0.0                # relative units (sum of tool cost weights + 1 LLM call)
    intents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "requires_tools": self.requires_tools, "planner": self.planner,
                "rationale": self.rationale, "estimated_cost": round(self.estimated_cost, 3),
                "intents": self.intents, "graph": self.graph.to_dict()}
