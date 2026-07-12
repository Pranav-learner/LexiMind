"""Verification & Reasoning API (Step 13) — thin transport over VerificationService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/verification`. Verification is
LLM-free in `fast` mode; `thorough` mode's single optional critique reuses the Module-1
`get_agent_services` answer function (overridden to a fake in tests) — the same single inference
pathway as the rest of the platform. No new LLM orchestration is introduced.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.api import get_agent_services
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.reasoning.errors import VerificationError
from app.reasoning.repository import VerificationRepository
from app.reasoning.schemas import (
    VerificationDetailOut,
    VerificationLogOut,
    VerificationStatsOut,
    VerifyRequest,
    VerifyTaskRequest,
)
from app.reasoning.service import VerificationService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/verification", tags=["verification"])


def _service(db: Session) -> VerificationService:
    return VerificationService(VerificationRepository(db))


def _handle(fn):
    try:
        return fn()
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- verify (ad-hoc)
@router.post("/verify", response_model=dict)
def verify(workspace_id: str, req: VerifyRequest, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db), services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    answer_fn = services.get("answer_fn") if req.mode == "thorough" else None
    return _handle(lambda: _service(db).verify(
        workspace_id, owner_id, answer_text=req.answer,
        evidence=[e.model_dump() for e in req.evidence], mode=req.mode, signals=req.signals,
        answer_fn=answer_fn, execution_id=req.execution_id, persist=req.persist))


# ----------------------------------------------------------------- verify a stored agent task
@router.post("/tasks/{task_id}/verify", response_model=dict)
def verify_task(workspace_id: str, task_id: str, req: VerifyTaskRequest,
                owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                services=Depends(get_agent_services)):
    _verify_workspace(db, workspace_id, owner_id)
    answer_fn = services.get("answer_fn") if req.mode == "thorough" else None
    return _handle(lambda: _service(db).verify_stored_task(
        workspace_id, owner_id, task_id, mode=req.mode, answer_fn=answer_fn))


# ----------------------------------------------------------------- reads / slices
@router.get("", response_model=list[VerificationLogOut])
def history(workspace_id: str, limit: int = Query(30, ge=1, le=100),
            owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [VerificationLogOut.model_validate(x) for x in _service(db).history(workspace_id, owner_id, limit=limit)]


@router.get("/stats", response_model=VerificationStatsOut)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return VerificationStatsOut(**_service(db).stats(workspace_id))


@router.get("/tasks/{task_id}", response_model=VerificationDetailOut)
def for_task(workspace_id: str, task_id: str, owner_id: str = Depends(get_current_user_id),
             db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return VerificationDetailOut.model_validate(_handle(lambda: _service(db).for_execution(task_id, owner_id)))


@router.get("/{verification_id}", response_model=VerificationDetailOut)
def detail(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return VerificationDetailOut.model_validate(_handle(lambda: _service(db).get(verification_id, owner_id)))


# ----------------------------------------------------------------- report slices (developer inspection)
def _report_or_404(db, workspace_id, verification_id, owner_id) -> dict:
    _verify_workspace(db, workspace_id, owner_id)
    log = _handle(lambda: _service(db).get(verification_id, owner_id))
    return log.report or {}


@router.get("/{verification_id}/confidence", response_model=dict)
def confidence(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    return _report_or_404(db, workspace_id, verification_id, owner_id).get("confidence", {})


@router.get("/{verification_id}/contradictions", response_model=list)
def contradictions(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    return _report_or_404(db, workspace_id, verification_id, owner_id).get("contradictions", [])


@router.get("/{verification_id}/citations", response_model=list)
def citation_issues(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    return _report_or_404(db, workspace_id, verification_id, owner_id).get("citation_issues", [])


@router.get("/{verification_id}/evidence-map", response_model=dict)
def evidence_map(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
                 db: Session = Depends(get_db)):
    r = _report_or_404(db, workspace_id, verification_id, owner_id)
    return {"evidence": r.get("evidence", []), "claim_verdicts": r.get("claim_verdicts", [])}


@router.get("/{verification_id}/explanation", response_model=dict)
def explanation(workspace_id: str, verification_id: str, owner_id: str = Depends(get_current_user_id),
                db: Session = Depends(get_db)):
    return _report_or_404(db, workspace_id, verification_id, owner_id).get("explanations", {})
