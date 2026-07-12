"""Agent Governance (Step 10) — the safety rails around a multi-agent run.

Validated BEFORE scheduling so an unsafe/oversized/looping workflow never executes:
- allowed agents        — only registered specialized agents (+ the verification step).
- workflow size quota   — bounded node count (execution quota) and dependency depth (recursion/loop guard).
- loop / recursion      — a dependency cycle is rejected (via `TaskGraph.layers()`), and a node may not
                          depend on itself.
- permissions / tools   — the per-run granted permissions + allowed-tools carried down to every node
                          (each node's `AgentTaskService.run_task` re-checks them through the Module-1
                          PermissionManager — governance never re-implements permission logic).

Future enterprise approval hooks (human-in-the-loop) plug in behind `GovernancePolicy` without changing
the scheduler. Quotas are conservative defaults; a workspace/plan tier can override them later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.orchestration.errors import GovernanceError
from app.orchestration.interfaces import AGENT_TYPES, TaskGraph

MAX_NODES = 24
MAX_DEPTH = 8          # longest dependency chain — recursion/runaway guard
MAX_WIDTH = 12         # widest parallel layer — resource limit


@dataclass
class GovernancePolicy:
    max_nodes: int = MAX_NODES
    max_depth: int = MAX_DEPTH
    max_width: int = MAX_WIDTH
    allowed_agents: List[str] = field(default_factory=lambda: list(AGENT_TYPES))
    granted_permissions: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None

    def validate(self, graph: TaskGraph) -> None:
        if not graph.nodes:
            raise GovernanceError("Workflow has no tasks.")
        if len(graph.nodes) > self.max_nodes:
            raise GovernanceError(f"Workflow exceeds the {self.max_nodes}-task quota ({len(graph.nodes)}).")
        ids = [n.id for n in graph.nodes]
        if len(ids) != len(set(ids)):
            raise GovernanceError("Duplicate task ids in the workflow.")
        id_set = set(ids)
        for n in graph.nodes:
            if n.agent not in self.allowed_agents:
                raise GovernanceError(f"Agent '{n.agent}' is not permitted (node {n.id}).")
            if n.id in n.depends_on:
                raise GovernanceError(f"Task {n.id} depends on itself (recursion).")
            for dep in n.depends_on:
                if dep not in id_set:
                    raise GovernanceError(f"Task {n.id} depends on unknown task '{dep}'.")
        # cycle detection + depth/width (layers raises on a cycle)
        try:
            depth = graph.depth()
        except ValueError as e:
            raise GovernanceError(str(e))
        if depth > self.max_depth:
            raise GovernanceError(f"Workflow depth {depth} exceeds the max depth {self.max_depth} (loop guard).")
        if graph.max_width() > self.max_width:
            raise GovernanceError(f"Workflow parallel width exceeds the limit {self.max_width}.")
