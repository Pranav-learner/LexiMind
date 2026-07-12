"""AI Observability & Monitoring API (Step 12) — thin transport over ObservabilityService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/observability`. The unified telemetry /
metrics / cost / health / alerts read the EXISTING logs (no re-logging); `trace-query` runs an
instrumented real pipeline (reuses Module-1 `get_agent_services` for the single answer function).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.observability.errors import ObservabilityError
from app.observability.schemas import CreateRuleRequest, TracedQueryRequest
from app.observability.service import ObservabilityService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/observability", tags=["observability"])


def _service(db: Session) -> ObservabilityService:
    return ObservabilityService(db)


def _handle(fn):
    try:
        return fn()
    except ObservabilityError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- dashboard + telemetry feed + metrics
@router.get("/dashboard", response_model=dict)
def dashboard(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).dashboard(workspace_id, owner_id)


@router.get("/events", response_model=list)
def events(workspace_id: str, source: str | None = Query(None), limit: int = Query(200, ge=1, le=1000),
           owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).events(workspace_id, owner_id, source=source, limit=limit)


@router.get("/metrics", response_model=dict)
def metrics(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).metrics_summary(workspace_id, owner_id)


@router.get("/cost", response_model=dict)
def cost(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).cost_report(workspace_id, owner_id)


@router.get("/health", response_model=dict)
def health(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).health_summary(workspace_id, owner_id)


# ----------------------------------------------------------------- distributed traces
@router.get("/traces", response_model=list)
def traces(workspace_id: str, limit: int = Query(50, ge=1, le=200),
           owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).traces(workspace_id, owner_id, limit=limit)


@router.get("/traces/{trace_id}", response_model=dict)
def trace_detail(workspace_id: str, trace_id: str, owner_id: str = Depends(get_current_user_id),
                 db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).trace_detail(trace_id, owner_id))


@router.post("/trace-query", response_model=dict)
def trace_query(workspace_id: str, req: TracedQueryRequest, owner_id: str = Depends(get_current_user_id),
                db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).run_traced_query(workspace_id, owner_id, question=req.question, services=services,
                                         hops=req.hops)


# ----------------------------------------------------------------- alerts
@router.get("/alerts/rules", response_model=list)
def list_rules(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).rules(workspace_id, owner_id)


@router.post("/alerts/rules", response_model=dict)
def create_rule(workspace_id: str, req: CreateRuleRequest, owner_id: str = Depends(get_current_user_id),
                db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).create_rule(owner_id, workspace_id, name=req.name, metric=req.metric,
                                    comparator=req.comparator, threshold=req.threshold, severity=req.severity)


@router.delete("/alerts/rules/{rule_id}", response_model=dict)
def delete_rule(workspace_id: str, rule_id: str, owner_id: str = Depends(get_current_user_id),
                db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete_rule(rule_id, owner_id))
    return {"deleted": rule_id}


@router.post("/alerts/evaluate", response_model=dict)
def evaluate_alerts(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).evaluate_alerts(workspace_id, owner_id)


@router.get("/alerts", response_model=list)
def alert_history(workspace_id: str, limit: int = Query(50, ge=1, le=200),
                  owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).alert_history(workspace_id, owner_id, limit=limit)
