"""AI Evaluation & Benchmarking API (Step 12) — thin transport over EvaluationService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/evaluation`. Benchmarks execute the REAL
production pipelines; the answer pipeline + LLM judge reuse the Module-1 `get_agent_services` (single
answer function), overridden in tests with a fake — no new inference path. CI-friendly: the run response
carries the regression report + gate result.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.evaluation.errors import EvaluationError
from app.evaluation.schemas import (
    CompareRequest,
    CreateDatasetRequest,
    ImportDatasetRequest,
    RegressionRequest,
    RunBenchmarkRequest,
)
from app.evaluation.service import EvaluationService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/evaluation", tags=["evaluation"])


def _service(db: Session) -> EvaluationService:
    return EvaluationService(db)


def _handle(fn):
    try:
        return fn()
    except EvaluationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- datasets
@router.post("/datasets", response_model=dict)
def create_dataset(workspace_id: str, req: CreateDatasetRequest, owner_id: str = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).create_dataset(
        owner_id, workspace_id, name=req.name, description=req.description, tags=req.tags,
        items=[i.model_dump() for i in req.items]))


@router.post("/datasets/import", response_model=dict)
def import_dataset(workspace_id: str, req: ImportDatasetRequest, owner_id: str = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).import_dataset(owner_id, workspace_id, req.model_dump()))


@router.get("/datasets", response_model=list)
def list_datasets(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).list_datasets(workspace_id, owner_id)


@router.get("/datasets/{dataset_id}/export", response_model=dict)
def export_dataset(workspace_id: str, dataset_id: str, owner_id: str = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).export_dataset(owner_id, dataset_id))


@router.get("/pipelines", response_model=list)
def pipelines(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).pipelines()


# ----------------------------------------------------------------- run benchmark
@router.post("/run", response_model=dict)
def run_benchmark(workspace_id: str, req: RunBenchmarkRequest, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).run_benchmark(
        owner_id, workspace_id, dataset_id=req.dataset_id, pipeline=req.pipeline, services=services,
        use_judge=req.use_judge, label=req.label, thresholds=req.thresholds, use_cache=req.use_cache))


# ----------------------------------------------------------------- history / regression / comparison / dashboard
@router.get("/runs", response_model=list)
def runs(workspace_id: str, dataset_id: str | None = Query(None), pipeline: str | None = Query(None),
         owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).history(workspace_id, owner_id, dataset_id=dataset_id, pipeline=pipeline)


@router.get("/runs/{run_id}", response_model=dict)
def run_detail(workspace_id: str, run_id: str, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).get_run(run_id, owner_id))


@router.post("/runs/{run_id}/regression", response_model=dict)
def regression(workspace_id: str, run_id: str, req: RegressionRequest = RegressionRequest(),
               owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).regression_report(run_id, owner_id, baseline_run_id=req.baseline_run_id))


@router.post("/compare", response_model=dict)
def compare(workspace_id: str, req: CompareRequest, owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).compare(req.a_run_id, req.b_run_id, owner_id))


@router.get("/dashboard", response_model=dict)
def dashboard(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).dashboard(workspace_id, owner_id)
