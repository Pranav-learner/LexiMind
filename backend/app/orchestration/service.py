"""Orchestration service — run a multi-agent workflow + persist telemetry + expose reads.

Thin coordination over the `Orchestrator` (execution) and the repository (OrchestrationExecutionLog).
Reuses the SAME injected external dependencies (`services`: the single answer function + the async
generation runners) as every other agent surface — one inference pathway for the whole platform.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.orchestration.errors import OrchestrationNotFound, OrchestrationStateError
from app.orchestration.governance import GovernancePolicy
from app.orchestration.models import OrchestrationExecutionLog
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.planner import TaskPlanner
from app.orchestration.registry import list_templates
from app.orchestration.repository import OrchestrationRepository


class OrchestrationService:
    def __init__(self, repo: OrchestrationRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ run
    def run(self, owner_id: str, workspace_id: str, *, objective: str, services: Dict[str, Any],
            document_ids: Optional[List[str]] = None, workflow: Optional[str] = None,
            graph: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None,
            granted_permissions: Optional[List[str]] = None,
            allowed_tools: Optional[List[str]] = None) -> Dict[str, Any]:
        governance = GovernancePolicy(granted_permissions=granted_permissions, allowed_tools=allowed_tools)
        orch = Orchestrator(self.db, owner_id, workspace_id, services=services, governance=governance)
        result = orch.run(objective=objective, document_ids=document_ids or [], params=params or {},
                          workflow=workflow, graph_override=graph)
        self._persist(owner_id, workspace_id, result)
        return result

    def _persist(self, owner_id: str, workspace_id: str, result: Dict[str, Any]) -> None:
        sched = result["schedule"]
        t = result["timings"]
        fv = result.get("final_verification") or {}
        conf = ((fv.get("confidence") or {}).get("overall") if isinstance(fv.get("confidence"), dict)
                else fv.get("confidence")) or 0.0
        log = OrchestrationExecutionLog(
            id=result["orchestration_id"], workspace_id=workspace_id, owner_id=owner_id,
            objective=result["objective"][:8000], workflow=result["workflow"], planner=result["planner"],
            status=result["status"], graph=result["graph"], agents_used=result["agents_used"],
            messages=result["timeline"], node_results=result["node_results"],
            node_count=len(result["graph"].get("nodes", [])), parallel_tasks=sched["parallel_tasks"],
            completed_tasks=sched["completed"], failed_tasks=sched["failed"],
            skipped_tasks=sched["skipped"], recovered_tasks=sched["recovered"], retries=sched["retries"],
            llm_calls=result["llm_calls"], token_usage=result["token_usage"],
            cost_estimate=result["cost_estimate"], planner_ms=t["planner_ms"], schedule_ms=t["schedule_ms"],
            aggregate_ms=t["aggregate_ms"], total_ms=t["total_ms"], output=result["output"],
            final_verification=fv or None, verification_status=(fv.get("status") or "unknown"),
            verification_confidence=float(conf or 0.0))
        self.repo.save(log)

    # ------------------------------------------------------------------ plan preview (no execution)
    def plan(self, objective: str, *, document_ids: Optional[List[str]] = None,
             params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return TaskPlanner().decompose(objective, document_ids=document_ids or [],
                                       params=params or {}).to_dict()

    def templates(self) -> List[Dict[str, Any]]:
        return list_templates()

    # ------------------------------------------------------------------ reads
    def get(self, orchestration_id: str, owner_id: str) -> OrchestrationExecutionLog:
        log = self.repo.get(orchestration_id, owner_id)
        if log is None:
            raise OrchestrationNotFound(orchestration_id)
        return log

    def history(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[OrchestrationExecutionLog]:
        return self.repo.list(workspace_id, owner_id, limit=limit)

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.stats(workspace_id)

    # ------------------------------------------------------------------ retry / cancel
    def retry(self, orchestration_id: str, owner_id: str, *, services: Dict[str, Any]) -> Dict[str, Any]:
        log = self.get(orchestration_id, owner_id)
        return self.run(owner_id, log.workspace_id, objective=log.objective, services=services,
                        workflow=(log.workflow if log.workflow != "custom" else None))

    def cancel(self, orchestration_id: str, owner_id: str) -> OrchestrationExecutionLog:
        log = self.get(orchestration_id, owner_id)
        if log.status not in ("running",):
            raise OrchestrationStateError(f"Cannot cancel a '{log.status}' orchestration.")
        log.status = "cancelled"
        self.db.commit(); self.db.refresh(log)
        return log
