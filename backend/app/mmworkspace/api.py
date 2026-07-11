"""Multimodal Workspace HTTP routes — the unified product surface.

Authenticated + workspace-scoped. The `ingest` endpoint is the "upload anything → automatic
processing" flow: it REUSES the document upload helper (create + text-index) then auto-enqueues
Module-1 multimodal processing + Module-2 vision — the user never chooses a pipeline. Every other
endpoint aggregates the existing domains (assets, timeline, pipeline status, AI actions, overview).
No business logic or tables are duplicated.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.mmworkspace.errors import WorkspaceAIError
from app.mmworkspace.schemas import (
    AiActionRequest,
    AiActionResponse,
    AssetExplorerResponse,
    IngestItemResult,
    IngestResponse,
    PipelineStatus,
    TimelineResponse,
    WorkspaceOverview,
)
from app.mmworkspace.service import WorkspaceOrchestrator
from app.workspaces.repository import WorkspaceRepository

# Injected dependencies (their tests overrides supply fakes/inline runners; calling the getters
# directly would bypass those overrides — so they MUST be resolved via Depends).
from app.documents.api import get_index_context, get_ingestor
from app.flashcards.api import get_flashcards_runner
from app.ingestion.api import get_ingestion_runner
from app.notes.api import get_notes_runner
from app.summaries.api import get_summary_runner
from app.vision.api import get_vision_runner

router = APIRouter(prefix="/workspaces/{workspace_id}/ai", tags=["workspace-ai"])


def _handle(fn):
    try:
        return fn()
    except WorkspaceAIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- unified ingest (auto pipelines)
@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest(
    workspace_id: str,
    files: List[UploadFile] = File(...),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
    ingestor=Depends(get_ingestor),
    ing_runner=Depends(get_ingestion_runner),
    vis_runner=Depends(get_vision_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    # Reuse the exact document-upload flow (create + validate + text-index), then chain the
    # multimodal + vision pipelines — importing the transport helper (no duplicated logic).
    from app.documents.api import _process_one_upload, _service as doc_service
    from app.ingestion.repository import IngestionRepository
    from app.ingestion.service import IngestionService
    from app.vision.repository import VisionRepository
    from app.vision.service import VisionService

    vector_store, bm25 = index_ctx
    service = doc_service(db)

    items: List[IngestItemResult] = []
    for upload in files:
        try:
            res = await _process_one_upload(service, vector_store, bm25, ingestor, workspace_id, owner_id, upload)
        except Exception as e:  # keep the batch alive
            items.append(IngestItemResult(filename=upload.filename or "untitled", success=False, error=str(e)))
            continue
        if not res.success or res.document is None:
            items.append(IngestItemResult(filename=res.filename, success=False, error=res.error))
            continue
        doc = res.document
        # Auto multimodal processing (Module 1).
        pjob = IngestionService(IngestionRepository(db)).create_or_get_job(owner_id, workspace_id, doc.id)
        ing_runner.submit(pjob.id)
        # Auto vision understanding (Module 2). With the inline runners this runs AFTER processing; in
        # production a job-completion chain guarantees ordering (see docs).
        vjob = VisionService(VisionRepository(db)).create_or_get_job(owner_id, workspace_id, doc.id)
        vis_runner.submit(vjob.id)
        items.append(IngestItemResult(
            filename=res.filename, success=True, document_id=doc.id, display_name=doc.display_name,
            processing_job_id=pjob.id, vision_job_id=vjob.id,
            media_kind="image" if doc.file_type in ("png", "jpg", "jpeg", "webp", "tiff", "tif") else "pdf"))

    uploaded = sum(1 for i in items if i.success)
    return IngestResponse(uploaded=uploaded, failed=len(items) - uploaded, items=items)


# ----------------------------------------------------------------- asset explorer
@router.get("/assets", response_model=AssetExplorerResponse)
def assets(workspace_id: str, asset_type: str | None = Query(None), limit: int = Query(60, ge=1, le=200),
           owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return AssetExplorerResponse(**WorkspaceOrchestrator(db).assets(workspace_id, owner_id, asset_type=asset_type, limit=limit))


# ----------------------------------------------------------------- workspace timeline
@router.get("/timeline", response_model=TimelineResponse)
def timeline(workspace_id: str, limit: int = Query(40, ge=1, le=100),
             owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TimelineResponse(items=WorkspaceOrchestrator(db).timeline(workspace_id, owner_id, limit=limit))


# ----------------------------------------------------------------- unified pipeline status
@router.get("/pipeline-status/{document_id}", response_model=PipelineStatus)
def pipeline_status(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return PipelineStatus(**_handle(lambda: WorkspaceOrchestrator(db).pipeline_status(workspace_id, owner_id, document_id)))


# ----------------------------------------------------------------- AI workspace actions
@router.post("/action", response_model=AiActionResponse)
def ai_action(
    workspace_id: str, req: AiActionRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    summary_runner=Depends(get_summary_runner), notes_runner=Depends(get_notes_runner),
    flashcard_runner=Depends(get_flashcards_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    result = _handle(lambda: WorkspaceOrchestrator(db).ai_action(
        workspace_id, owner_id, req.action, req.document_id, focus=req.focus, count=req.count,
        summary_runner=summary_runner, notes_runner=notes_runner, flashcard_runner=flashcard_runner))
    return AiActionResponse(**result)


# ----------------------------------------------------------------- overview / observability
@router.get("/overview", response_model=WorkspaceOverview)
def overview(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return WorkspaceOverview(**WorkspaceOrchestrator(db).overview(workspace_id, owner_id))
