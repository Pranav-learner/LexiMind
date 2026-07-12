"""Multi-Agent Orchestration interfaces (Phase 6, Module 4) — the coordination value objects + seams.

The orchestrator turns a user objective into a TEAM of specialized agents working a shared task graph.
It owns NO agent/retrieval/inference logic — it schedules `AgentTaskService.run_task` (which already
reuses retrieval → context → PromptPackage → AnswerService → verification) per node, then merges the
results through ONE final PromptPackage → AnswerService call.

Value objects (serializable dataclasses):
- `TaskNode`         — one agent task in the graph (agent type + objective + deps + scheduling policy +
                       failure policy) plus runtime telemetry (status/attempts/latency/produced task id).
- `TaskGraph`        — a serializable DAG of TaskNodes; `layers()` topo-sorts into parallel groups and
                       `validate()` enforces governance (no cycles / bounded size + depth).
- `OrchestrationPlan`— objective + graph + planner metadata.
- `AgentMessage`     — a STRUCTURED message on the communication bus (artifacts only — never chain-of-thought).

Protocols: TaskPlanner · Scheduler · ResultAggregator — each replaceable (heuristic now, richer later).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

# node lifecycle
PENDING, RUNNING, OK, FAILED, SKIPPED, RECOVERED, CANCELLED = (
    "pending", "running", "ok", "failed", "skipped", "recovered", "cancelled")

# the agent types the orchestrator can schedule (specialized agents + the verification step)
AGENT_TYPES = ("research", "writing", "comparison", "study", "verification")


@dataclass
class TaskNode:
    id: str
    agent: str                             # research | writing | comparison | study | verification
    objective: Optional[str] = None         # per-node objective (defaults to the workflow objective)
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    mode: str = "parallel"                  # parallel | sequential (within its dependency layer)
    optional: bool = False                  # failure of an optional node never aborts the workflow
    priority: int = 5                       # 1 (highest) .. 9 (lowest) — scheduling order within a layer
    retries: int = 1                        # attempts on failure (failure recovery)
    timeout_s: float = 120.0
    fallback: Optional[str] = None           # agent type to try if this node fails
    forward_evidence: bool = True            # reuse upstream evidence (avoid duplicate retrieval)

    # --- runtime telemetry (filled during scheduling) ---
    status: str = PENDING
    attempts: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None
    task_id: Optional[str] = None            # the AgentTaskLog id this node produced
    result_summary: str = ""
    recovered_by: Optional[str] = None        # set when a fallback agent recovered the node

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "agent": self.agent, "objective": self.objective, "params": self.params,
                "depends_on": self.depends_on, "mode": self.mode, "optional": self.optional,
                "priority": self.priority, "retries": self.retries, "timeout_s": self.timeout_s,
                "fallback": self.fallback, "forward_evidence": self.forward_evidence,
                "status": self.status, "attempts": self.attempts, "latency_ms": round(self.latency_ms, 3),
                "error": self.error, "task_id": self.task_id, "result_summary": self.result_summary,
                "recovered_by": self.recovered_by}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskNode":
        return TaskNode(
            id=d["id"], agent=d["agent"], objective=d.get("objective"), params=d.get("params", {}),
            depends_on=d.get("depends_on", []), mode=d.get("mode", "parallel"),
            optional=d.get("optional", False), priority=d.get("priority", 5), retries=d.get("retries", 1),
            timeout_s=d.get("timeout_s", 120.0), fallback=d.get("fallback"),
            forward_evidence=d.get("forward_evidence", True), status=d.get("status", PENDING),
            attempts=d.get("attempts", 0), latency_ms=d.get("latency_ms", 0.0), error=d.get("error"),
            task_id=d.get("task_id"), result_summary=d.get("result_summary", ""),
            recovered_by=d.get("recovered_by"))


@dataclass
class TaskGraph:
    nodes: List[TaskNode] = field(default_factory=list)

    def add(self, node: TaskNode) -> TaskNode:
        self.nodes.append(node)
        return node

    def by_id(self, node_id: str) -> Optional[TaskNode]:
        return next((n for n in self.nodes if n.id == node_id), None)

    def layers(self) -> List[List[TaskNode]]:
        """Topologically order nodes into dependency layers (each layer is independently parallelizable)."""
        remaining = {n.id: n for n in self.nodes}
        done: set = set()
        layers: List[List[TaskNode]] = []
        while remaining:
            ready = [n for n in remaining.values() if all(dep in done for dep in n.depends_on)]
            if not ready:
                raise ValueError("Task graph has a dependency cycle or a missing dependency.")
            # schedule higher-priority (lower number) first inside a layer
            ready.sort(key=lambda n: n.priority)
            layers.append(ready)
            for n in ready:
                done.add(n.id); del remaining[n.id]
        return layers

    def depth(self) -> int:
        return len(self.layers()) if self.nodes else 0

    def max_width(self) -> int:
        return max((len(l) for l in self.layers()), default=0) if self.nodes else 0

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes]}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskGraph":
        return TaskGraph(nodes=[TaskNode.from_dict(n) for n in (d or {}).get("nodes", [])])


@dataclass
class OrchestrationPlan:
    objective: str
    graph: TaskGraph
    planner: str = "heuristic-v1"
    workflow: str = "custom"
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"objective": self.objective, "planner": self.planner, "workflow": self.workflow,
                "rationale": self.rationale, "graph": self.graph.to_dict()}


@dataclass
class AgentMessage:
    seq: int
    at_ms: float
    sender: str                            # node id or "orchestrator"
    recipient: str                         # node id or "all"
    type: str                              # task_request | result | status | error | shared_ref
    payload: Dict[str, Any] = field(default_factory=dict)   # STRUCTURED artifacts only (no chain-of-thought)

    def to_dict(self) -> Dict[str, Any]:
        return {"seq": self.seq, "at_ms": round(self.at_ms, 3), "sender": self.sender,
                "recipient": self.recipient, "type": self.type, "payload": self.payload}


# --------------------------------------------------------------------- protocols
class TaskPlanner(Protocol):
    name: str
    def decompose(self, objective: str, *, document_ids: List[str], params: Dict[str, Any]) -> OrchestrationPlan: ...


class Scheduler(Protocol):
    def run(self, graph: TaskGraph, *, run_node, bus, cancel_flag=None) -> Dict[str, Any]: ...


class ResultAggregator(Protocol):
    def aggregate(self, objective: str, results: List[Any], *, answer_fn=None) -> Dict[str, Any]: ...
