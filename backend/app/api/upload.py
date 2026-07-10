import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user_id
from app.core.config import settings
from app.core.state import bm25_retriever, vector_store
from app.db.base import get_db
from app.services.ingestion_service import ingest_pdf
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = settings.upload_dir
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    # Phase 3: an upload MAY be bound to a workspace. Optional for backward compatibility —
    # a request with no workspace_id behaves exactly as before (global, workspace-less).
    workspace_id: Optional[str] = Form(None),
    owner_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    workspace_id = (workspace_id or "").strip() or None

    # If a workspace is named, it must exist and (when authenticated) belong to the caller.
    if workspace_id is not None:
        service = WorkspaceService(WorkspaceRepository(db))
        ws = WorkspaceRepository(db).get(workspace_id, owner_id) if owner_id else None
        if owner_id and ws is None:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Ingestion (extract -> chunk -> enrich metadata -> batch embed -> index) lives in
    # the ingestion service; the route only handles transport + workspace bookkeeping.
    result = ingest_pdf(file_path, file.filename, vector_store, bm25_retriever, workspace_id=workspace_id)

    # Keep the workspace's denormalized document_count accurate (one document per upload).
    if workspace_id is not None and owner_id is not None and result.get("total_chunks", 0) > 0:
        service.adjust_counter(workspace_id, owner_id, "document_count", 1)

    return result
