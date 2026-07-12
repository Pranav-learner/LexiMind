"""Graph Reasoning & Explainable AI API (Step 13) — thin transport over GraphReasoningService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/reasoning`. Reasoning is LLM-free (it
reasons over the graph); optional conclusion verification reuses the Phase-6 Verification Engine.
Consistent with the graph / memory / verification developer APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.graphreason.errors import ReasoningError
from app.graphreason.schemas import (
    ExplainRequest,
    PreviewRequest,
    ReasonRequest,
    ReasoningLogOut,
    RootCauseRequest,
)
from app.graphreason.service import GraphReasoningService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/reasoning", tags=["graph-reasoning"])


def _service(db: Session) -> GraphReasoningService:
    return GraphReasoningService(db)


def _handle(fn):
    try:
        return fn()
    except ReasoningError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- reason
@router.post("/reason", response_model=dict)
def reason(workspace_id: str, req: ReasonRequest, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).reason(workspace_id, owner_id, query=req.query, hops=req.hops, directed=req.directed,
                               verify=req.verify, dependency=req.dependency, seed_entity_ids=req.seed_entity_ids)


@router.post("/preview", response_model=dict)
def preview(workspace_id: str, req: PreviewRequest, owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).preview(workspace_id, owner_id, query=req.query, hops=req.hops)


@router.post("/root-cause", response_model=dict)
def root_cause(workspace_id: str, req: RootCauseRequest, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).root_cause(workspace_id, owner_id, query=req.query)


@router.post("/explain", response_model=dict)
def explain(workspace_id: str, req: ExplainRequest, owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).explain(workspace_id, owner_id, query=req.query, hops=req.hops)


@router.get("/entities/{entity_id}/dependencies", response_model=dict)
def dependencies(workspace_id: str, entity_id: str, hops: int = Query(5, ge=1, le=6),
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).dependency_analysis(workspace_id, owner_id, entity_id, hops=hops))


# ----------------------------------------------------------------- reads
@router.get("/inferred", response_model=list[dict])
def inferred(workspace_id: str, limit: int = Query(100, ge=1, le=500),
             owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).inferred(workspace_id, owner_id, limit=limit)


@router.get("/stats", response_model=dict)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).stats(workspace_id)


@router.get("/logs", response_model=list[ReasoningLogOut])
def logs(workspace_id: str, limit: int = Query(30, ge=1, le=100),
         owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [ReasoningLogOut.model_validate(x) for x in _service(db).logs(workspace_id, owner_id, limit=limit)]
