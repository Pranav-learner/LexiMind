"""Agent service — orchestrates a run + persists telemetry + exposes discovery/history/retry/cancel.

Thin coordination over the runtime (execution) + the repository (AgentExecutionLog). Builds the
`AgentContext` from the request + the injected external dependencies (`services`: the single answer
function + the async runners). Contains no tool/business logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.context import AgentContext
from app.agents.errors import AgentStateError, ExecutionNotFound
from app.agents.models import AgentExecutionLog
from app.agents.permissions import PermissionManager
from app.agents.planner import HeuristicPlanner
from app.agents.registry import agent_registry, tool_registry
from app.agents.repository import AgentRepository
from app.agents.runtime import AgentRuntime


class AgentService:
    def __init__(self, repo: AgentRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ run
    def run(self, owner_id: str, workspace_id: str, *, query: str, services: Dict[str, Any],
            conversation_id: Optional[str] = None, document_id: Optional[str] = None,
            granted_permissions: Optional[List[str]] = None, allowed_tools: Optional[List[str]] = None,
            agent: str = "workspace_agent") -> Dict[str, Any]:
        ctx = AgentContext(
            db=self.db, owner_id=owner_id, workspace_id=workspace_id, query=query, agent=agent,
            conversation_id=conversation_id, document_id=document_id, services=services,
            granted_permissions=granted_permissions or [], allowed_tools=allowed_tools)
        permissions = PermissionManager(granted_permissions or None, allowed_tools=allowed_tools)
        result = AgentRuntime().run(ctx, permissions=permissions)
        self._persist(ctx, result)
        return result

    def _persist(self, ctx: AgentContext, result: Dict[str, Any]) -> None:
        t = result["timings"]
        status = "completed" if result["success"] else ("failed")
        log = AgentExecutionLog(
            id=result["execution_id"], workspace_id=ctx.workspace_id, owner_id=ctx.owner_id,
            agent=result["agent"], query=ctx.query[:4000], conversation_id=ctx.conversation_id,
            document_id=ctx.document_id, status=status, success=result["success"],
            cancelled=(result["phase"] == "cancelled"), error=result.get("error"),
            planner=result["plan"]["planner"], requires_tools=result["plan"]["requires_tools"],
            tool_count=result["tool_count"], retry_count=result["retry_count"],
            estimated_cost=result["estimated_cost"], graph=result["plan"], timeline=result["timeline"],
            planner_ms=t["planner_ms"], tools_ms=t["tools_ms"], llm_ms=t["llm_ms"], total_ms=t["total_ms"],
            token_usage=result["token_usage"], cost_estimate=result["estimated_cost"])
        self.repo.save(log)

    # ------------------------------------------------------------------ planner preview (no execution)
    def planner_preview(self, owner_id: str, workspace_id: str, *, query: str,
                        document_id: Optional[str] = None) -> Dict[str, Any]:
        ctx = AgentContext(db=self.db, owner_id=owner_id, workspace_id=workspace_id, query=query,
                           document_id=document_id)
        return HeuristicPlanner().plan(ctx).to_dict()

    # ------------------------------------------------------------------ discovery
    def tools(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in tool_registry().specs()]

    def tool(self, name: str) -> Dict[str, Any]:
        return tool_registry().spec(name).to_dict()

    def agents(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in agent_registry().all()]

    # ------------------------------------------------------------------ history / logs
    def get(self, execution_id: str, owner_id: str) -> AgentExecutionLog:
        log = self.repo.get(execution_id, owner_id)
        if log is None:
            raise ExecutionNotFound(execution_id)
        return log

    def history(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[AgentExecutionLog]:
        return self.repo.list(workspace_id, owner_id, limit=limit)

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.stats(workspace_id)

    # ------------------------------------------------------------------ retry / cancel
    def retry(self, execution_id: str, owner_id: str, *, services: Dict[str, Any]) -> Dict[str, Any]:
        log = self.get(execution_id, owner_id)
        return self.run(owner_id, log.workspace_id, query=log.query, services=services,
                        conversation_id=log.conversation_id, document_id=log.document_id, agent=log.agent)

    def cancel(self, execution_id: str, owner_id: str) -> AgentExecutionLog:
        log = self.get(execution_id, owner_id)
        if log.status not in ("running",):
            # Synchronous runs are already terminal by the time a cancel arrives; kept for the async future.
            raise AgentStateError(f"Cannot cancel a '{log.status}' execution.")
        log.status = "cancelled"; log.cancelled = True
        self.db.commit(); self.db.refresh(log)
        return log
