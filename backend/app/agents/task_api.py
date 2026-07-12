"""Specialized-agent task API (Step 13) — thin transport over AgentTaskService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/agent-tasks`. It REUSES the Module-1
`get_agent_services` dependency (the single answer function + the async generation runners) so tests
substitute a faked answer + inline runners exactly as they do for the Module-1 runtime — one injection
surface for the whole agent platform.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.agents.errors import AgentError
from app.agents.task_repository import AgentTaskRepository
from app.agents.task_schemas import (
    ComparisonRequest,
    ExportOut,
    PreviewRequest,
    ResearchRequest,
    StudyRequest,
    TaskDetailOut,
    TaskLogOut,
    TaskStatsOut,
    WorkflowRunRequest,
    WritingRequest,
)
from app.agents.task_service import AgentTaskService
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/agent-tasks", tags=["agent-tasks"])


def _service(db: Session) -> AgentTaskService:
    return AgentTaskService(AgentTaskRepository(db))


def _handle(fn):
    try:
        return fn()
    except AgentError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _common(req) -> dict:
    p = {}
    if getattr(req, "top_k", None) is not None:
        p["top_k"] = req.top_k
    if getattr(req, "verify", None) is not None:
        p["verify"] = req.verify
    return p


# ----------------------------------------------------------------- run: research
@router.post("/research", response_model=dict)
def run_research(workspace_id: str, req: ResearchRequest,
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                 services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    params = _common(req)
    if req.evidence_limit is not None:
        params["evidence_limit"] = req.evidence_limit
    return _handle(lambda: _service(db).run(
        owner_id, workspace_id, task_type="research", objective=req.objective, services=services,
        document_ids=req.document_ids, params=params, conversation_id=req.conversation_id,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools).to_dict())


# ----------------------------------------------------------------- run: writing
@router.post("/writing", response_model=dict)
def run_writing(workspace_id: str, req: WritingRequest,
                owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    params = _common(req); params["doc_type"] = req.doc_type
    return _handle(lambda: _service(db).run(
        owner_id, workspace_id, task_type="writing", objective=req.objective, services=services,
        document_ids=req.document_ids, params=params, conversation_id=req.conversation_id,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools).to_dict())


# ----------------------------------------------------------------- run: comparison
@router.post("/comparison", response_model=dict)
def run_comparison(workspace_id: str, req: ComparisonRequest,
                   owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                   services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    params = _common(req)
    if req.targets:
        params["targets"] = [t.model_dump(exclude_none=True) for t in req.targets]
    return _handle(lambda: _service(db).run(
        owner_id, workspace_id, task_type="comparison", objective=req.objective, services=services,
        document_ids=req.document_ids, params=params, conversation_id=req.conversation_id,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools).to_dict())


# ----------------------------------------------------------------- run: study
@router.post("/study", response_model=dict)
def run_study(workspace_id: str, req: StudyRequest,
              owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
              services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    params = _common(req)
    if req.deliverables is not None:
        params["deliverables"] = req.deliverables
    if req.subject:
        params["subject"] = req.subject
    return _handle(lambda: _service(db).run(
        owner_id, workspace_id, task_type="study", objective=req.objective, services=services,
        document_ids=req.document_ids, params=params, conversation_id=req.conversation_id,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools).to_dict())


# ----------------------------------------------------------------- run: workflow
@router.post("/workflows/{name}/run", response_model=dict)
def run_workflow(workspace_id: str, name: str, req: WorkflowRunRequest,
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                 services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    params = {**req.params, **_common(req)}
    return _handle(lambda: _service(db).run_workflow(
        owner_id, workspace_id, name=name, objective=req.objective, services=services,
        document_ids=req.document_ids, params=params, definition_override=req.definition_override))


# ----------------------------------------------------------------- preview (no execution)
@router.post("/preview", response_model=dict)
def preview(workspace_id: str, req: PreviewRequest,
            owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).preview(
        owner_id, workspace_id, task_type=req.task_type, objective=req.objective,
        document_ids=req.document_ids, params=req.params))


# ----------------------------------------------------------------- discovery
@router.get("/agents", response_model=list[str])
def list_specialized_agents(workspace_id: str, owner_id: str = Depends(get_current_user_id),
                            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).agents()


@router.get("/workflows", response_model=list[dict])
def list_wf(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).workflows()


# ----------------------------------------------------------------- history / status
@router.get("", response_model=list[TaskLogOut])
def history(workspace_id: str, limit: int = Query(30, ge=1, le=100),
            task_type: str | None = Query(None), owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [TaskLogOut.model_validate(x)
            for x in _service(db).history(workspace_id, owner_id, limit=limit, task_type=task_type)]


@router.get("/stats", response_model=TaskStatsOut)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TaskStatsOut(**_service(db).stats(workspace_id))


@router.get("/{task_id}", response_model=TaskDetailOut)
def detail(workspace_id: str, task_id: str, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TaskDetailOut.model_validate(_handle(lambda: _service(db).get(task_id, owner_id)))


@router.get("/{task_id}/export", response_model=ExportOut)
def export(workspace_id: str, task_id: str, format: str = Query("markdown", pattern="^(markdown|json)$"),
           owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ExportOut(**_handle(lambda: _service(db).export(task_id, owner_id, fmt=format)))


# ----------------------------------------------------------------- retry / cancel
@router.post("/{task_id}/retry", response_model=dict)
def retry(workspace_id: str, task_id: str, owner_id: str = Depends(get_current_user_id),
          db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).retry(task_id, owner_id, services=services).to_dict())


@router.post("/{task_id}/cancel", response_model=TaskLogOut)
def cancel(workspace_id: str, task_id: str, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TaskLogOut.model_validate(_handle(lambda: _service(db).cancel(task_id, owner_id)))
