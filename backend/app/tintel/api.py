"""Temporal-intelligence HTTP routes — thin transport over TemporalIntelService.

Authenticated + workspace-scoped, nested under a media document. Reads auto-derive on demand
(`ensure_derived`); `POST .../temporal-intelligence/derive` forces (re)derivation. These are the
canonical chapter/topic/event endpoints that Module 2 will later back with richer data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.tintel.errors import TemporalIntelError
from app.tintel.repository import TemporalIntelRepository
from app.tintel.schemas import (
    ChapterOut,
    DeriveRequest,
    DeriveResponse,
    TimelineEventOut,
    TopicOut,
)
from app.tintel.service import TemporalIntelService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/media/{document_id}", tags=["temporal-intelligence"])


def _service(db: Session) -> TemporalIntelService:
    return TemporalIntelService(TemporalIntelRepository(db))


def _handle(fn):
    try:
        return fn()
    except TemporalIntelError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


@router.get("/chapters", response_model=list[ChapterOut])
def list_chapters(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [ChapterOut.model_validate(c) for c in
            _handle(lambda: _service(db).chapters(document_id, owner_id, workspace_id))]


@router.get("/topics", response_model=list[TopicOut])
def list_topics(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [TopicOut.model_validate(t) for t in
            _handle(lambda: _service(db).topics(document_id, owner_id, workspace_id))]


@router.get("/events", response_model=list[TimelineEventOut])
def list_events(
    workspace_id: str, document_id: str, event_type: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    return [TimelineEventOut.model_validate(e) for e in
            _handle(lambda: _service(db).events(document_id, owner_id, workspace_id, event_type))]


@router.post("/temporal-intelligence/derive", response_model=DeriveResponse)
def derive(
    workspace_id: str, document_id: str, req: DeriveRequest = DeriveRequest(),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    counts = _handle(lambda: _service(db).derive(document_id, owner_id, workspace_id, force=req.force))
    return DeriveResponse(document_id=document_id, **counts)
