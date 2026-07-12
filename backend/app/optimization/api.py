"""AI Optimization & Cost Intelligence API (Step 12) — thin transport over OptimizationService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/optimization`. Preview/recommend endpoints
run only the decision layer (no pipeline); `run` applies the plan through the real pipeline (reusing
Module-1 `get_agent_services` for the single answer function). Consistent with the observability/evaluation
API shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.optimization.errors import OptimizationError
from app.optimization.schemas import OptimizeRequest, SetPolicyRequest
from app.optimization.service import OptimizationService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/optimization", tags=["optimization"])


def _service(db: Session) -> OptimizationService:
    return OptimizationService(db)


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _handle(fn):
    try:
        return fn()
    except OptimizationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


# ----------------------------------------------------------------- decision layer (no execution)
@router.post("/preview", response_model=dict)
def preview(workspace_id: str, req: OptimizeRequest, owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).preview(workspace_id, owner_id, query=req.query, policy=req.policy))


@router.post("/recommend/model", response_model=dict)
def recommend_model(workspace_id: str, req: OptimizeRequest, owner_id: str = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).recommend_model(workspace_id, owner_id, query=req.query, policy=req.policy))


@router.post("/recommend/pipeline", response_model=dict)
def recommend_pipeline(workspace_id: str, req: OptimizeRequest, owner_id: str = Depends(get_current_user_id),
                       db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).recommend_pipeline(workspace_id, owner_id, query=req.query, policy=req.policy))


# ----------------------------------------------------------------- optimized execution
@router.post("/run", response_model=dict)
def run_optimized(workspace_id: str, req: OptimizeRequest, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).run_optimized(workspace_id, owner_id, query=req.query,
                                                      services=services, policy=req.policy))


# ----------------------------------------------------------------- cost / quality / history
@router.get("/dashboard", response_model=dict)
def dashboard(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).dashboard(workspace_id, owner_id)


@router.get("/cost", response_model=dict)
def cost_analysis(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).cost_analysis(workspace_id, owner_id)


@router.get("/quality-vs-cost", response_model=dict)
def quality_vs_cost(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).quality_vs_cost(workspace_id, owner_id)


@router.get("/history", response_model=list)
def history(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).history(workspace_id, owner_id)


@router.get("/cache", response_model=dict)
def cache_stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).cache_stats(workspace_id, owner_id)


# ----------------------------------------------------------------- policy management
@router.get("/policy", response_model=dict)
def get_policy(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).get_policy(workspace_id, owner_id)


@router.put("/policy", response_model=dict)
def set_policy(workspace_id: str, req: SetPolicyRequest, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).set_policy(workspace_id, owner_id, policy=req.policy))
