"""Reading-session HTTP routes (Phase 3, Module 3).

A separate router (`/workspaces/{id}/reading`) so its static `history` path never collides with
the documents router's `/{document_id}` param routes. Every route is authenticated and verifies
both workspace ownership and (for progress) that the document belongs to the caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.documents.errors import DocumentError
from app.documents.reading import ReadingService, ReadingSessionRepository
from app.documents.repository import DocumentRepository
from app.documents.schemas import (
    ReadingHistoryItem,
    ReadingHistoryResponse,
    ReadingProgressUpdate,
    ReadingSessionOut,
)
from app.documents.service import DocumentService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/reading", tags=["reading"])


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _get_document(db: Session, document_id: str, owner_id: str):
    try:
        return DocumentService(DocumentRepository(db)).get(document_id, owner_id)
    except DocumentError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _reading(db: Session) -> ReadingService:
    return ReadingService(ReadingSessionRepository(db))


@router.put("/{document_id}/progress", response_model=ReadingSessionOut)
def save_progress(
    workspace_id: str,
    document_id: str,
    req: ReadingProgressUpdate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    doc = _get_document(db, document_id, owner_id)
    rs = _reading(db).save_progress(
        owner_id, doc.workspace_id, doc.id,
        page=req.page, scroll_top=req.scroll_top, zoom=req.zoom, rotation=req.rotation,
    )
    return ReadingSessionOut.model_validate(rs)


@router.get("/{document_id}/progress", response_model=ReadingSessionOut | None)
def get_progress(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Return the saved reading position for session restore, or null if none yet."""
    _verify_workspace(db, workspace_id, owner_id)
    doc = _get_document(db, document_id, owner_id)
    rs = _reading(db).get(owner_id, doc.id)
    return ReadingSessionOut.model_validate(rs) if rs else None


@router.get("/history", response_model=ReadingHistoryResponse)
def reading_history(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    _verify_workspace(db, workspace_id, owner_id)
    rows = _reading(db).history(owner_id, workspace_id, limit=limit)
    items = [
        ReadingHistoryItem(
            document_id=doc.id,
            display_name=doc.display_name,
            filename=doc.filename,
            file_type=doc.file_type,
            page=rs.page,
            page_count=doc.page_count,
            updated_at=rs.updated_at,
        )
        for rs, doc in rows
    ]
    return ReadingHistoryResponse(items=items)
