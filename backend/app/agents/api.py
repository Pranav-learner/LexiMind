"""Agent framework HTTP routes (Step 13) — thin transport over AgentService.

Authenticated + workspace-scoped. The single answer function + the async generation runners are
injected via `Depends` (`get_agent_services`) so `app.agents.api` imports with no LLM/faiss/torch and
tests substitute a faked answer + inline runners. Consistent with the chat / media-ai APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.errors import AgentError
from app.agents.repository import AgentRepository
from app.agents.schemas import (
    AgentDescriptorOut,
    ExecutionDetail,
    ExecutionLogOut,
    PlannerPreviewRequest,
    RunAgentRequest,
    RunAgentResponse,
    StatsResponse,
    ToolSpecOut,
)
from app.agents.service import AgentService
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/agent", tags=["agent"])


# ----------------------------------------------------------------- injected external dependencies
def get_agent_services():
    """The runtime's external deps: the SINGLE answer function + the existing async runners. Overridden
    in tests with a faked answer (no LLM) + inline runners (synchronous generation)."""
    from app.flashcards.runner import FlashcardRunner
    from app.notes.runner import NoteRunner
    from app.services import answer_service
    from app.summaries.runner import SummaryRunner
    return {"answer_fn": answer_service.complete, "summary_runner": SummaryRunner(),
            "notes_runner": NoteRunner(), "flashcard_runner": FlashcardRunner()}


def _service(db: Session) -> AgentService:
    return AgentService(AgentRepository(db))


def _handle(fn):
    try:
        return fn()
    except AgentError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- run
@router.post("/run", response_model=RunAgentResponse)
def run_agent(
    workspace_id: str, req: RunAgentRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    services=Depends(get_agent_services),
):
    _verify_workspace(db, workspace_id, owner_id)
    return RunAgentResponse(**_handle(lambda: _service(db).run(
        owner_id, workspace_id, query=req.query, services=services, agent=req.agent,
        conversation_id=req.conversation_id, document_id=req.document_id,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools)))


# ----------------------------------------------------------------- planner preview (no execution)
@router.post("/plan", response_model=dict)
def planner_preview(workspace_id: str, req: PlannerPreviewRequest, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).planner_preview(owner_id, workspace_id, query=req.query, document_id=req.document_id)


# ----------------------------------------------------------------- discovery
@router.get("/tools", response_model=list[ToolSpecOut])
def list_tools(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [ToolSpecOut(**t) for t in _service(db).tools()]


@router.get("/tools/{name}", response_model=ToolSpecOut)
def get_tool(workspace_id: str, name: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ToolSpecOut(**_handle(lambda: _service(db).tool(name)))


@router.get("/agents", response_model=list[AgentDescriptorOut])
def list_agents(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [AgentDescriptorOut(**a) for a in _service(db).agents()]


# ----------------------------------------------------------------- history / logs / status
@router.get("/executions", response_model=list[ExecutionLogOut])
def history(workspace_id: str, limit: int = Query(30, ge=1, le=100), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [ExecutionLogOut.model_validate(x) for x in _service(db).history(workspace_id, owner_id, limit=limit)]


@router.get("/executions/{execution_id}", response_model=ExecutionDetail)
def execution_detail(workspace_id: str, execution_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ExecutionDetail.model_validate(_handle(lambda: _service(db).get(execution_id, owner_id)))


@router.get("/executions/{execution_id}/graph", response_model=dict)
def execution_graph(workspace_id: str, execution_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    log = _handle(lambda: _service(db).get(execution_id, owner_id))
    return log.graph or {"nodes": []}


@router.get("/stats", response_model=StatsResponse)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return StatsResponse(**_service(db).stats(workspace_id))


# ----------------------------------------------------------------- retry / cancel
@router.post("/executions/{execution_id}/retry", response_model=RunAgentResponse)
def retry_execution(
    workspace_id: str, execution_id: str, owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db), services=Depends(get_agent_services),
):
    _verify_workspace(db, workspace_id, owner_id)
    return RunAgentResponse(**_handle(lambda: _service(db).retry(execution_id, owner_id, services=services)))


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionLogOut)
def cancel_execution(workspace_id: str, execution_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ExecutionLogOut.model_validate(_handle(lambda: _service(db).cancel(execution_id, owner_id)))
