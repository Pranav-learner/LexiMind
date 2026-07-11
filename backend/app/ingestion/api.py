"""Multimodal ingestion HTTP routes — thin transport over IngestionService + a background runner.

Authenticated + workspace-scoped. Processing is asynchronous: `POST .../process` returns a `queued`
job and hands the id to the injected runner; the client polls `GET .../processing`. The runner (and
the engine it wraps) are injected lazily so `app.ingestion.api` imports with no OCR/vision libs and
tests substitute an inline runner + fake engine.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.ingestion.errors import IngestionError
from app.ingestion.repository import IngestionRepository
from app.ingestion.schemas import (
    AssetsResponse,
    ExtractedFigureOut,
    ExtractedImageOut,
    ExtractedTableOut,
    JobDetail,
    MultimodalChunkOut,
    OcrPageOut,
    OcrStatusResponse,
    ProcessingJobOut,
    ProcessingLogOut,
    ProcessRequest,
)
from app.ingestion.service import IngestionService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["ingestion"])

_runner = None


def get_ingestion_runner():
    global _runner
    if _runner is None:
        from app.ingestion.runner import IngestionRunner
        _runner = IngestionRunner()
    return _runner


def _service(db: Session) -> IngestionService:
    return IngestionService(IngestionRepository(db))


def _handle(fn):
    try:
        return fn()
    except IngestionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _job_out(job) -> ProcessingJobOut:
    return ProcessingJobOut.model_validate(job)


# ----------------------------------------------------------------- process (async)
@router.post("/documents/{document_id}/process", response_model=ProcessingJobOut, status_code=202)
def process_document(
    workspace_id: str, document_id: str, req: ProcessRequest = ProcessRequest(),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    runner=Depends(get_ingestion_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).create_or_get_job(owner_id, workspace_id, document_id, force=req.force))
    if job.status in ("queued",):
        runner.submit(job.id)
        db.refresh(job)
    return _job_out(job)


# ----------------------------------------------------------------- document-level status / assets
@router.get("/documents/{document_id}/processing", response_model=ProcessingJobOut | None)
def document_processing_status(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).status_for_document(document_id, owner_id, workspace_id))
    return _job_out(job) if job else None


@router.get("/documents/{document_id}/assets", response_model=AssetsResponse)
def document_assets(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    images, tables, figures = _handle(lambda: _service(db).assets(document_id, owner_id, workspace_id))
    return AssetsResponse(
        images=[ExtractedImageOut.model_validate(i) for i in images],
        tables=[ExtractedTableOut.model_validate(t) for t in tables],
        figures=[ExtractedFigureOut.model_validate(f) for f in figures],
    )


@router.get("/documents/{document_id}/ocr", response_model=OcrStatusResponse)
def document_ocr(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    rows, avg = _handle(lambda: _service(db).ocr_status(document_id, owner_id, workspace_id))
    lang = next((r.language for r in rows if r.language), "")
    return OcrStatusResponse(
        document_id=document_id, ocr_pages=len(rows), language=lang, avg_confidence=avg,
        pages=[OcrPageOut(page_number=r.page_number, text=r.text, confidence=r.confidence, language=r.language) for r in rows],
    )


@router.get("/documents/{document_id}/multimodal-chunks", response_model=list[MultimodalChunkOut])
def document_chunks(
    workspace_id: str, document_id: str, chunk_type: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    chunks = _handle(lambda: _service(db).chunks(document_id, owner_id, workspace_id, chunk_type))
    return [MultimodalChunkOut.model_validate(c) for c in chunks]


# ----------------------------------------------------------------- job-level (detail / retry / cancel)
@router.get("/processing/{job_id}", response_model=JobDetail)
def job_detail(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job, logs = _handle(lambda: _service(db).detail(job_id, owner_id))
    d = JobDetail.model_validate(job)
    d.logs = [ProcessingLogOut.model_validate(x) for x in logs]
    return d


@router.post("/processing/{job_id}/retry", response_model=ProcessingJobOut)
def retry_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), runner=Depends(get_ingestion_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).retry(job_id, owner_id))
    runner.submit(job.id)
    db.refresh(job)
    return _job_out(job)


@router.post("/processing/{job_id}/cancel", response_model=ProcessingJobOut)
def cancel_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _job_out(_handle(lambda: _service(db).cancel(job_id, owner_id)))
