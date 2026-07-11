"""Knowledge Dashboard & Analytics HTTP routes — thin transport over AnalyticsService.

Authenticated + workspace-scoped, read-only. Every section is cached (signature + TTL) so the
dashboard is cheap on repeat loads. No AI runner — aggregation is synchronous and cached.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics.errors import AnalyticsError
from app.analytics.repository import AnalyticsRepository
from app.analytics.service import AnalyticsService
from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/dashboard", tags=["analytics"])


def _service(db: Session) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(db))


def _handle(fn):
    try:
        return fn()
    except AnalyticsError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- full overview
@router.get("")
def dashboard(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).dashboard(workspace_id, owner_id)


# ----------------------------------------------------------------- individual sections
@router.get("/knowledge")
def knowledge(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).section(workspace_id, owner_id, "knowledge")


@router.get("/ai-usage")
def ai_usage(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).section(workspace_id, owner_id, "ai_usage")


@router.get("/learning")
def learning(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).section(workspace_id, owner_id, "learning")


@router.get("/retrieval")
def retrieval(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).section(workspace_id, owner_id, "retrieval")


@router.get("/charts")
def charts(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).section(workspace_id, owner_id, "charts")


@router.get("/activity")
def activity(workspace_id: str, type: str | None = Query(None), limit: int = Query(40, ge=1, le=100),
             owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    items = _service(db).section(workspace_id, owner_id, "activity").get("items", [])
    if type:
        items = [e for e in items if e.get("type") == type]
    return {"items": items[:limit]}


@router.get("/insights")
def insights(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return {"items": _service(db).insights(workspace_id, owner_id)}


# ----------------------------------------------------------------- documents
@router.get("/documents")
def documents(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return {"items": _service(db).documents(workspace_id, owner_id)}


@router.get("/documents/{document_id}")
def document(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).document(workspace_id, owner_id, document_id))


# ----------------------------------------------------------------- refresh (bust cache)
@router.post("/refresh")
def refresh(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).refresh(workspace_id, owner_id)
