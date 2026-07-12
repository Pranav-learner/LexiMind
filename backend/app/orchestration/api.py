"""Multi-Agent Orchestration API (Step 14) — thin transport over OrchestrationService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/orchestration`. Reuses the Module-1
`get_agent_services` dependency (single answer function + async runners) so tests substitute a faked
answer + inline runners — the same one injection surface as the whole agent platform.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.orchestration.errors import OrchestrationError
from app.orchestration.repository import OrchestrationRepository
from app.orchestration.schemas import (
    OrchestrationDetailOut,
    OrchestrationLogOut,
    OrchestrationStatsOut,
    PlanRequest,
    RunWorkflowRequest,
)
from app.orchestration.service import OrchestrationService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/orchestration", tags=["orchestration"])


def _service(db: Session) -> OrchestrationService:
    return OrchestrationService(OrchestrationRepository(db))


def _handle(fn):
    try:
        return fn()
    except OrchestrationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- run
@router.post("/run", response_model=dict)
def run_workflow(workspace_id: str, req: RunWorkflowRequest,
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                 services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).run(
        owner_id, workspace_id, objective=req.objective, services=services,
        document_ids=req.document_ids, workflow=req.workflow, graph=req.graph, params=req.params,
        granted_permissions=req.granted_permissions, allowed_tools=req.allowed_tools))


# ----------------------------------------------------------------- plan preview (no execution)
@router.post("/plan", response_model=dict)
def plan(workspace_id: str, req: PlanRequest, owner_id: str = Depends(get_current_user_id),
         db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).plan(req.objective, document_ids=req.document_ids, params=req.params)


# ----------------------------------------------------------------- templates
@router.get("/templates", response_model=list[dict])
def templates(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).templates()


# ----------------------------------------------------------------- history / status
@router.get("", response_model=list[OrchestrationLogOut])
def history(workspace_id: str, limit: int = Query(30, ge=1, le=100),
            owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [OrchestrationLogOut.model_validate(x) for x in _service(db).history(workspace_id, owner_id, limit=limit)]


@router.get("/stats", response_model=OrchestrationStatsOut)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return OrchestrationStatsOut(**_service(db).stats(workspace_id))


@router.get("/{orchestration_id}", response_model=OrchestrationDetailOut)
def detail(workspace_id: str, orchestration_id: str, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return OrchestrationDetailOut.model_validate(_handle(lambda: _service(db).get(orchestration_id, owner_id)))


@router.get("/{orchestration_id}/graph", response_model=dict)
def graph(workspace_id: str, orchestration_id: str, owner_id: str = Depends(get_current_user_id),
          db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).get(orchestration_id, owner_id)).graph or {"nodes": []}


@router.get("/{orchestration_id}/timeline", response_model=list)
def timeline(workspace_id: str, orchestration_id: str, owner_id: str = Depends(get_current_user_id),
             db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).get(orchestration_id, owner_id)).messages or []


# ----------------------------------------------------------------- retry / cancel
@router.post("/{orchestration_id}/retry", response_model=dict)
def retry(workspace_id: str, orchestration_id: str, owner_id: str = Depends(get_current_user_id),
          db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).retry(orchestration_id, owner_id, services=services))


@router.post("/{orchestration_id}/cancel", response_model=OrchestrationLogOut)
def cancel(workspace_id: str, orchestration_id: str, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return OrchestrationLogOut.model_validate(_handle(lambda: _service(db).cancel(orchestration_id, owner_id)))
