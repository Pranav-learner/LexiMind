"""Specialized-agent task service (Steps 3–7, 12–14) — the coordination layer.

Builds the request-scoped `AgentContext` (+ task memory + event sink + the framework `ToolExecutor`),
dispatches to the right specialized agent (or runs a workflow of them), persists an `AgentTaskLog`, and
exposes preview / history / retry / cancel / export. It reuses the SAME injected external dependencies
as the Module-1 runtime (`services`: the single answer function + the async generation runners), so the
whole platform keeps ONE inference pathway and one set of generation runners. Contains no agent or
retrieval logic — that lives in the specialized agents (which delegate to the existing services).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.context import AgentContext
from app.agents.errors import AgentStateError, ExecutionNotFound
from app.agents.events import InMemoryEventSink
from app.agents.executor import ToolExecutor
from app.agents.models import AgentTaskLog
from app.agents.permissions import PermissionManager
from app.agents.registry import tool_registry
from app.agents.specialized.base import AgentTask, AgentTaskResult
from app.agents.specialized.registry import available, get_agent
from app.agents.specialized.research_agent import derive_subquestions
from app.agents.specialized.task_memory import TaskMemory
from app.agents.specialized.workflows import WorkflowEngine, get_workflow, list_workflows
from app.agents.task_repository import AgentTaskRepository


class AgentTaskService:
    def __init__(self, repo: AgentTaskRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ run one task
    def run_task(self, task: AgentTask, *, services: Dict[str, Any],
                 granted_permissions: Optional[List[str]] = None, allowed_tools: Optional[List[str]] = None,
                 conversation_id: Optional[str] = None, workflow: Optional[str] = None,
                 parent_task_id: Optional[str] = None, persist: bool = True) -> AgentTaskResult:
        ctx = AgentContext(
            db=self.db, owner_id=task.owner_id, workspace_id=task.workspace_id, query=task.objective,
            agent=task.task_type, conversation_id=conversation_id, document_id=task.primary_document,
            params={**task.params, "document_ids": task.document_ids}, services=services,
            granted_permissions=granted_permissions or [], allowed_tools=allowed_tools)
        ctx.execution_id = task.task_id
        ctx.memory = TaskMemory()
        ctx.events = InMemoryEventSink()
        permissions = PermissionManager(granted_permissions or None, allowed_tools=allowed_tools)
        executor = ToolExecutor(tool_registry(), permissions)

        agent = get_agent(task.task_type)
        ctx.agent = agent.name
        result = agent.run(task, ctx, executor=executor, events=ctx.events)

        # Phase-6 M3 — every specialized agent auto-verifies (configurable fast/thorough; off to skip).
        # Reuses the SAME ctx (answer_fn) + the evidence the agent already gathered — no re-retrieval,
        # no second LLM orchestration. Verification never fails the task (trust layer, not a gate).
        verify_mode = str(task.params.get("verify", "fast")).lower()
        if verify_mode in ("fast", "thorough") and result.success:
            try:
                from app.reasoning.repository import VerificationRepository
                from app.reasoning.service import VerificationService
                vsvc = VerificationService(VerificationRepository(self.db))
                result.verification = vsvc.verify_task_result(result, ctx, mode=verify_mode,
                                                              persist=persist)
            except Exception as e:  # verification is advisory — degrade, never crash the task
                result.verification = {"status": "warning", "error": f"verification failed: {e}"}

        if persist:
            self._persist(task, result, workflow=workflow, parent_task_id=parent_task_id,
                          conversation_id=conversation_id)
        return result

    # ------------------------------------------------------------------ convenience entrypoints
    def run(self, owner_id: str, workspace_id: str, *, task_type: str, objective: str,
            services: Dict[str, Any], document_ids: Optional[List[str]] = None,
            params: Optional[Dict[str, Any]] = None, conversation_id: Optional[str] = None,
            granted_permissions: Optional[List[str]] = None,
            allowed_tools: Optional[List[str]] = None) -> AgentTaskResult:
        task = AgentTask(task_type=task_type, objective=objective, workspace_id=workspace_id,
                         owner_id=owner_id, document_ids=document_ids or [], params=params or {},
                         conversation_id=conversation_id)
        return self.run_task(task, services=services, granted_permissions=granted_permissions,
                             allowed_tools=allowed_tools, conversation_id=conversation_id)

    # ------------------------------------------------------------------ workflow
    def run_workflow(self, owner_id: str, workspace_id: str, *, name: str, objective: str,
                     services: Dict[str, Any], document_ids: Optional[List[str]] = None,
                     params: Optional[Dict[str, Any]] = None,
                     definition_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if definition_override:
            from app.agents.specialized.workflows import WorkflowDefinition
            definition = WorkflowDefinition.from_dict(definition_override)
        else:
            definition = get_workflow(name)

        def _run(task: AgentTask) -> AgentTaskResult:
            return self.run_task(task, services=services, workflow=definition.name)

        engine = WorkflowEngine(run_task=_run)
        out = engine.run(definition, objective=objective, workspace_id=workspace_id, owner_id=owner_id,
                         document_ids=document_ids or [], base_params=params or {})
        # strip the non-serializable AgentTaskResult objects from the response
        out.pop("results", None)
        return out

    # ------------------------------------------------------------------ preview (no execution / no LLM)
    def preview(self, owner_id: str, workspace_id: str, *, task_type: str, objective: str,
                document_ids: Optional[List[str]] = None,
                params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        document_ids = document_ids or []
        if task_type == "research":
            subqs = derive_subquestions(objective)
            return {"task_type": task_type, "objective": objective, "plan": {"subquestions": subqs,
                    "tools": ["workspace_search"], "scope": "document" if document_ids else "workspace"}}
        if task_type == "writing":
            from app.agents.specialized.writing_agent import DEFAULT_DOC_TYPE, DOC_TYPES
            dt = params.get("doc_type") or params.get("report_type") or DEFAULT_DOC_TYPE
            spec = DOC_TYPES.get(dt, DOC_TYPES[DEFAULT_DOC_TYPE])
            return {"task_type": task_type, "objective": objective,
                    "plan": {"doc_type": dt, "outline": spec["outline"]}}
        if task_type == "comparison":
            targets = params.get("targets") or document_ids
            return {"task_type": task_type, "objective": objective,
                    "plan": {"targets": targets, "count": len(targets)}}
        if task_type == "study":
            from app.agents.specialized.study_agent import DEFAULT_DELIVERABLES
            return {"task_type": task_type, "objective": objective,
                    "plan": {"deliverables": params.get("deliverables") or DEFAULT_DELIVERABLES}}
        return {"task_type": task_type, "objective": objective, "plan": {}}

    # ------------------------------------------------------------------ discovery
    def agents(self) -> List[str]:
        return available()

    def workflows(self) -> List[Dict[str, Any]]:
        return list_workflows()

    # ------------------------------------------------------------------ persistence
    def _persist(self, task: AgentTask, result: AgentTaskResult, *, workflow: Optional[str],
                 parent_task_id: Optional[str], conversation_id: Optional[str]) -> None:
        status = ("completed" if result.success else
                  ("cancelled" if result.phase == "cancelled" else "failed"))
        out = result.output.to_dict() if result.output is not None else None
        log = AgentTaskLog(
            id=result.task_id, workspace_id=task.workspace_id, owner_id=task.owner_id, agent=result.agent,
            task_type=result.task_type, objective=task.objective[:8000], conversation_id=conversation_id,
            document_ids=task.document_ids or None, params=task.params or None, workflow=workflow,
            parent_task_id=parent_task_id, status=status, success=result.success,
            cancelled=(result.phase == "cancelled"), phase=result.phase, error=result.error,
            plan=result.plan, steps=[s.to_dict() for s in result.steps], timeline=result.timeline,
            output=out, knowledge_gaps=result.knowledge_gaps or None,
            output_format=result.output.format if result.output is not None else "markdown",
            evidence_count=len(result.evidence), citation_count=len(out["citations"]) if out else 0,
            tool_calls=result.tool_calls, retries=result.retries, documents_used=result.documents_used,
            media_used=result.media_used, workspace_used=result.workspace_used,
            planner_ms=result.timings.planner_ms, research_ms=result.timings.research_ms,
            analysis_ms=result.timings.analysis_ms, writing_ms=result.timings.writing_ms,
            total_ms=result.timings.total_ms, token_usage=result.token_usage,
            cost_estimate=result.estimated_cost)
        self.repo.save(log)

    # ------------------------------------------------------------------ history / logs
    def get(self, task_id: str, owner_id: str) -> AgentTaskLog:
        log = self.repo.get(task_id, owner_id)
        if log is None:
            raise ExecutionNotFound(task_id)
        return log

    def history(self, workspace_id: str, owner_id: str, *, limit: int = 30,
                task_type: Optional[str] = None) -> List[AgentTaskLog]:
        return self.repo.list(workspace_id, owner_id, limit=limit, task_type=task_type)

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.stats(workspace_id)

    # ------------------------------------------------------------------ retry / cancel / export
    def retry(self, task_id: str, owner_id: str, *, services: Dict[str, Any]) -> AgentTaskResult:
        log = self.get(task_id, owner_id)
        return self.run(owner_id, log.workspace_id, task_type=log.task_type, objective=log.objective,
                        services=services, document_ids=log.document_ids or [], params=log.params or {},
                        conversation_id=log.conversation_id)

    def cancel(self, task_id: str, owner_id: str) -> AgentTaskLog:
        log = self.get(task_id, owner_id)
        if log.status not in ("running",):
            raise AgentStateError(f"Cannot cancel a '{log.status}' task.")
        log.status = "cancelled"; log.cancelled = True; log.phase = "cancelled"
        self.db.commit(); self.db.refresh(log)
        return log

    def export(self, task_id: str, owner_id: str, *, fmt: str = "markdown") -> Dict[str, Any]:
        log = self.get(task_id, owner_id)
        output = log.output or {}
        if fmt == "json":
            return {"task_id": task_id, "format": "json", "content": output,
                    "filename": f"{log.task_type}-{task_id}.json"}
        # markdown (default) — the stored StructuredOutput already carries a rendered markdown field
        md = output.get("markdown") or f"# {log.objective}\n\n_(no output)_"
        return {"task_id": task_id, "format": "markdown", "content": md,
                "filename": f"{log.task_type}-{task_id}.md"}
