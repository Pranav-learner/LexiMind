"""Multi-Agent Orchestrator (Steps 1–2, 7, 16) — the conductor of the agent team.

Flow (owns NO agent/retrieval/inference logic — it composes the existing pieces):

    objective → TaskPlanner.decompose → GovernancePolicy.validate → AgentScheduler.run
              → (per node) AgentTaskService.run_task  [reuses retrieval→context→PromptPackage→AnswerService→verify]
              → SharedContextManager (evidence reuse, no re-retrieval)
              → ResultAggregator (ONE PromptPackage → ONE AnswerService call)
              → final VerificationService pass → OrchestrationExecutionLog

The scheduler dispatches through `run_node`, which builds an `AgentTask` and calls the Module-2
`AgentTaskService` (already the single per-agent pathway) — so the orchestrator never duplicates the AI
pipeline. Verification nodes reuse the Module-3 `VerificationService`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agents.specialized.base import AgentTask
from app.agents.specialized.outputs import StructuredOutput
from app.orchestration.aggregator import ResultAggregator
from app.orchestration.bus import CommunicationBus
from app.orchestration.governance import GovernancePolicy
from app.orchestration.interfaces import OK, RECOVERED, TaskGraph, TaskNode
from app.orchestration.planner import TaskPlanner
from app.orchestration.registry import get_template
from app.orchestration.scheduler import AgentScheduler
from app.orchestration.shared_context import SharedContextManager


@dataclass
class _VerificationResult:
    """A lightweight, aggregator-compatible result wrapper for a verification node."""
    agent: str = "verification"
    task_type: str = "verification"
    success: bool = True
    output: Any = None
    evidence: List[Any] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    token_usage: int = 0
    estimated_cost: float = 0.0
    task_id: Optional[str] = None


class Orchestrator:
    def __init__(self, db, owner_id: str, workspace_id: str, *, services: Dict[str, Any],
                 governance: Optional[GovernancePolicy] = None):
        self.db = db
        self.owner_id = owner_id
        self.workspace_id = workspace_id
        self.services = services or {}
        self.governance = governance or GovernancePolicy()
        self.planner = TaskPlanner()
        self.scheduler = AgentScheduler()
        self.aggregator = ResultAggregator()
        self.orchestration_id = f"orc_{uuid.uuid4().hex[:16]}"

    # ------------------------------------------------------------------ public
    def run(self, *, objective: str, document_ids: Optional[List[str]] = None,
            params: Optional[Dict[str, Any]] = None, workflow: Optional[str] = None,
            graph_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        document_ids = document_ids or []
        params = params or {}
        t0 = time.perf_counter()
        bus = CommunicationBus()
        shared = SharedContextManager()

        # 1) PLAN --------------------------------------------------------------
        p = time.perf_counter()
        if graph_override:
            graph, workflow_name, rationale = TaskGraph.from_dict(graph_override), params.get("workflow", "custom"), "custom graph"
        elif workflow:
            graph, workflow_name, rationale = get_template(workflow), workflow, f"template '{workflow}'"
        else:
            plan = self.planner.decompose(objective, document_ids=document_ids, params=params)
            graph, workflow_name, rationale = plan.graph, plan.workflow, plan.rationale
        planner_ms = (time.perf_counter() - p) * 1000

        # 2) GOVERN (validated BEFORE any execution) ---------------------------
        self.governance.validate(graph)
        bus.publish("orchestrator", "all", "status",
                    {"status": "planned", "detail": rationale, "nodes": len(graph.nodes)})

        # 3) SCHEDULE ----------------------------------------------------------
        parallel = bool(self.services.get("session_factory"))
        p = time.perf_counter()

        def run_node(node: TaskNode, agent: str) -> Dict[str, Any]:
            return self._run_node(node, agent, objective, document_ids, shared, bus, workflow_name, parallel)

        sched = self.scheduler.run(graph, run_node=run_node, bus=bus, parallel=parallel)
        schedule_ms = (time.perf_counter() - p) * 1000

        # 4) AGGREGATE — ONE unified PromptPackage → ONE AnswerService call -----
        p = time.perf_counter()
        results = shared.all_results()
        agg = self.aggregator.aggregate(objective, results, answer_fn=self.services.get("answer_fn"))
        aggregate_ms = (time.perf_counter() - p) * 1000

        # 5) FINAL VERIFICATION of the synthesized answer ----------------------
        final_ver = None
        verify_final = params.get("verify_final", True)
        if verify_final and agg.get("answer"):
            final_ver = self._final_verify(agg["answer"], agg["citations"],
                                           mode=params.get("verify_mode", "fast"))

        total_ms = (time.perf_counter() - t0) * 1000
        status = self._status(sched)
        llm_calls = sum(1 for n in graph.nodes if n.agent != "verification" and n.status in (OK, RECOVERED)) \
            + agg.get("llm_calls", 0)
        token_usage = sum(int(getattr(r, "token_usage", 0) or 0) for r in results)
        cost = round(sum(float(getattr(r, "estimated_cost", 0.0) or 0.0) for r in results) + 1.0, 3)

        return {
            "orchestration_id": self.orchestration_id, "objective": objective, "workflow": workflow_name,
            "status": status, "planner": self.planner.name, "rationale": rationale,
            "graph": graph.to_dict(), "agents_used": sorted({n.agent for n in graph.nodes if n.status in (OK, RECOVERED)}),
            "schedule": sched, "timeline": bus.timeline(), "shared_context": shared.snapshot(),
            "output": agg["output"], "answer": agg["answer"], "citations": agg["citations"],
            "combined_verification": agg["combined_verification"], "final_verification": final_ver,
            "node_results": [{"node": n.id, "agent": n.agent, "status": n.status, "task_id": n.task_id,
                              "summary": n.result_summary, "attempts": n.attempts,
                              "latency_ms": round(n.latency_ms, 3), "recovered_by": n.recovered_by,
                              "optional": n.optional} for n in graph.nodes],
            "llm_calls": llm_calls, "token_usage": token_usage, "cost_estimate": cost,
            "timings": {"planner_ms": round(planner_ms, 3), "schedule_ms": round(schedule_ms, 3),
                        "aggregate_ms": round(aggregate_ms, 3), "total_ms": round(total_ms, 3)},
        }

    # ------------------------------------------------------------------ node dispatch
    def _run_node(self, node: TaskNode, agent: str, objective: str, document_ids: List[str],
                  shared: SharedContextManager, bus: CommunicationBus, workflow_name: str,
                  parallel: bool) -> Dict[str, Any]:
        node_objective = node.objective or objective
        params = dict(node.params)
        # SHARED CONTEXT REUSE — feed upstream evidence to reuse-capable agents (no re-retrieval)
        if node.forward_evidence:
            dep_ev = shared.dependency_evidence(node)
            if dep_ev:
                params.setdefault("evidence", dep_ev)
                bus.shared_ref(node.id, "evidence", {"count": len(dep_ev), "from": node.depends_on})

        if agent == "verification":
            return self._run_verification_node(node, node_objective, shared, params)

        # specialized agent → the Module-2 single per-agent pathway
        svc, db = self._task_service(parallel)
        try:
            task = AgentTask(task_type=agent, objective=node_objective, workspace_id=self.workspace_id,
                             owner_id=self.owner_id, document_ids=document_ids, params=params)
            res = svc.run_task(task, services=self.services,
                               granted_permissions=self.governance.granted_permissions,
                               allowed_tools=self.governance.allowed_tools,
                               workflow=workflow_name, parent_task_id=self.orchestration_id)
        finally:
            if db is not None:
                db.close()
        shared.put_result(node.id, res)
        conf = (res.verification or {}).get("confidence", {}).get("overall") if res.verification else None
        return {"ok": bool(res.success), "task_id": res.task_id,
                "summary": (res.output.summary if res.output else ""),
                "evidence": len(res.evidence), "confidence": conf,
                "error": res.error if not res.success else None}

    def _run_verification_node(self, node: TaskNode, objective: str, shared: SharedContextManager,
                               params: Dict[str, Any]) -> Dict[str, Any]:
        """Verify the union of upstream deliverables (reuses Module-3 VerificationService)."""
        deps = [shared.get_result(d) for d in node.depends_on]
        deps = [d for d in deps if d is not None and getattr(d, "success", False)]
        if not deps:
            return {"ok": False, "error": "no upstream deliverables to verify"}
        answer_text = "\n\n".join(_answer_text(d) for d in deps)
        evidence: List[Any] = []
        for d in deps:
            evidence.extend(getattr(d, "evidence", []) or [])
        report = self._verification_service().verify(
            self.workspace_id, self.owner_id, answer_text=answer_text, evidence=evidence,
            mode=params.get("mode", "fast"), signals={"success": True},
            execution_id=self.orchestration_id, agent="verification", task_type="orchestration")
        out = StructuredOutput(title="Verification", summary=f"Workflow verification: {report['status']}")
        out.markdown(f"Status **{report['status']}**, confidence {report['confidence']['overall']:.0%}.")
        vr = _VerificationResult(output=out, verification=report)
        shared.put_result(node.id, vr)
        return {"ok": True, "task_id": None, "summary": out.summary,
                "evidence": 0, "confidence": report["confidence"]["overall"]}

    def _final_verify(self, answer: str, citations: List[Dict[str, Any]], *, mode: str) -> Dict[str, Any]:
        return self._verification_service().verify(
            self.workspace_id, self.owner_id, answer_text=answer, evidence=citations, mode=mode,
            signals={"success": True}, execution_id=self.orchestration_id, agent="orchestrator",
            task_type="orchestration")

    # ------------------------------------------------------------------ helpers
    def _task_service(self, parallel: bool):
        from app.agents.task_repository import AgentTaskRepository
        from app.agents.task_service import AgentTaskService
        if parallel and self.services.get("session_factory"):
            db = self.services["session_factory"]()
            return AgentTaskService(AgentTaskRepository(db)), db
        return AgentTaskService(AgentTaskRepository(self.db)), None

    def _verification_service(self):
        from app.reasoning.repository import VerificationRepository
        from app.reasoning.service import VerificationService
        return VerificationService(VerificationRepository(self.db))

    @staticmethod
    def _status(sched: Dict[str, Any]) -> str:
        if sched.get("cancelled"):
            return "cancelled"
        if sched.get("completed", 0) == 0:
            return "failed"
        return "partial" if sched.get("failed", 0) > 0 else "completed"


def _answer_text(result: Any) -> str:
    out = result.output.to_dict() if getattr(result, "output", None) is not None else {}
    for b in (out.get("blocks") or []):
        if b.get("type") == "markdown":
            return str(b.get("content") or "")
    return out.get("summary") or ""
