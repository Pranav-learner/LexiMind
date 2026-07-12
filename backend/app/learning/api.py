"""Continuous Learning & Feedback API (Step 13) — thin transport over LearningService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/learning`. Feedback submission accepts
authenticated users (the feedback store also supports anonymous rows at the model level). Recommendations
are always governed — the review endpoints only change status; nothing is auto-applied to production.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.learning.errors import LearningError
from app.learning.schemas import BuildDatasetRequest, FeedbackRequest, ReviewRequest
from app.learning.service import LearningService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/learning", tags=["learning"])


def _service(db: Session) -> LearningService:
    return LearningService(db)


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _handle(fn):
    try:
        return fn()
    except LearningError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


# ----------------------------------------------------------------- feedback
@router.post("/feedback", response_model=dict)
def submit_feedback(workspace_id: str, req: FeedbackRequest, owner_id: str = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).submit_feedback(workspace_id, owner_id, target_type=req.target_type,
                                        target_id=req.target_id, kind=req.kind, rating=req.rating,
                                        comment=req.comment, correction=req.correction, signals=req.signals)


@router.get("/feedback", response_model=list)
def feedback_history(workspace_id: str, sentiment: Optional[str] = Query(None),
                     limit: int = Query(100, ge=1, le=500), owner_id: str = Depends(get_current_user_id),
                     db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).feedback_history(workspace_id, owner_id, limit=limit, sentiment=sentiment)


@router.get("/feedback/summary", response_model=dict)
def feedback_summary(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).feedback_summary(workspace_id, owner_id)


# ----------------------------------------------------------------- insights + learning cycle
@router.get("/insights", response_model=dict)
def insights(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).insights(workspace_id, owner_id)


@router.post("/generate", response_model=dict)
def generate(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).generate(workspace_id, owner_id)


@router.post("/cycle", response_model=dict)
def run_cycle(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).run_cycle(workspace_id, owner_id)


# ----------------------------------------------------------------- review queue (governed)
@router.get("/recommendations", response_model=list)
def recommendations(workspace_id: str, status: str = Query("pending"), category: Optional[str] = Query(None),
                    limit: int = Query(100, ge=1, le=300), owner_id: str = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).recommendations(workspace_id, owner_id, status=status, category=category, limit=limit)


@router.get("/recommendations/{rec_id}", response_model=dict)
def recommendation(workspace_id: str, rec_id: str, owner_id: str = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).recommendation(rec_id, owner_id))


@router.post("/recommendations/{rec_id}/approve", response_model=dict)
def approve(workspace_id: str, rec_id: str, req: ReviewRequest, owner_id: str = Depends(get_current_user_id),
            db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).approve(rec_id, owner_id, note=req.note))


@router.post("/recommendations/{rec_id}/reject", response_model=dict)
def reject(workspace_id: str, rec_id: str, req: ReviewRequest, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).reject(rec_id, owner_id, note=req.note))


# ----------------------------------------------------------------- dataset builder + reports
@router.post("/dataset", response_model=dict)
def build_dataset(workspace_id: str, req: BuildDatasetRequest, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).build_dataset(workspace_id, owner_id, name=req.name)


@router.get("/report", response_model=dict)
def improvement_report(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).improvement_report(workspace_id, owner_id)


@router.get("/dashboard", response_model=dict)
def dashboard(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).dashboard(workspace_id, owner_id)
