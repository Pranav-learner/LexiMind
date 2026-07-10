"""Workspace HTTP routes — thin transport adapters over WorkspaceService.

Every route is authenticated (`get_current_user_id`) and scoped to that owner, so a user can
only ever see or mutate their own workspaces. Domain errors are translated to HTTP here;
no business logic lives in this file.
"""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.workspaces.errors import WorkspaceError
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.schemas import (
    ArchivedFilter,
    SortField,
    SortOrder,
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _service(db: Session) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(db))


def _handle(fn):
    try:
        return fn()
    except WorkspaceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    req: WorkspaceCreate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    ws = _handle(
        lambda: _service(db).create(
            owner_id,
            name=req.name,
            description=req.description,
            icon=req.icon,
            color=req.color,
        )
    )
    return WorkspaceOut.model_validate(ws)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    archived: ArchivedFilter = Query(ArchivedFilter.active),
    sort_by: SortField = Query(SortField.updated_at),
    order: SortOrder = Query(SortOrder.desc),
):
    items, total = _service(db).list(
        owner_id,
        page=page,
        page_size=page_size,
        search=search,
        archived=archived,
        sort_by=sort_by,
        order=order,
    )
    return WorkspaceListResponse(
        items=[WorkspaceOut.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    ws = _handle(lambda: _service(db).get(workspace_id, owner_id))
    return WorkspaceOut.model_validate(ws)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: str,
    req: WorkspaceUpdate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    ws = _handle(
        lambda: _service(db).update(
            workspace_id,
            owner_id,
            name=req.name,
            description=req.description,
            icon=req.icon,
            color=req.color,
        )
    )
    return WorkspaceOut.model_validate(ws)


@router.post("/{workspace_id}/archive", response_model=WorkspaceOut)
def archive_workspace(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    ws = _handle(lambda: _service(db).archive(workspace_id, owner_id))
    return WorkspaceOut.model_validate(ws)


@router.post("/{workspace_id}/restore", response_model=WorkspaceOut)
def restore_workspace(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    ws = _handle(lambda: _service(db).restore(workspace_id, owner_id))
    return WorkspaceOut.model_validate(ws)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    permanent: bool = Query(False, description="Hard-delete instead of the default soft-delete."),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _handle(lambda: _service(db).delete(workspace_id, owner_id, permanent=permanent))
    return None
