"""Vision Intelligence HTTP routes — thin transport over VisionService + a background runner.

Authenticated + workspace-scoped, read-mostly. Analysis is asynchronous: `POST .../vision` returns a
`queued` job and hands the id to the injected runner; the client polls `GET .../vision`. The runner
(and the CLIP/BLIP engine it wraps) are injected lazily so `app.vision.api` imports with no vision
libs and tests substitute an inline runner + fake engine.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.vision.errors import VisionError
from app.vision.repository import VisionRepository
from app.vision.schemas import (
    CaptionOut,
    SearchMetaItem,
    SearchMetaResponse,
    VisionAnalysisList,
    VisionAnalysisOut,
    VisionEmbeddingOut,
    VisionJobDetail,
    VisionJobOut,
    VisionProcessRequest,
)
from app.vision.service import VisionService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["vision"])

_runner = None


def get_vision_runner():
    global _runner
    if _runner is None:
        from app.vision.runner import VisionRunner
        _runner = VisionRunner()
    return _runner


def _service(db: Session) -> VisionService:
    return VisionService(VisionRepository(db))


def _handle(fn):
    try:
        return fn()
    except VisionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _job_out(job) -> VisionJobOut:
    return VisionJobOut.model_validate(job)


def _analysis_out(row, has_embedding=False) -> VisionAnalysisOut:
    o = VisionAnalysisOut.model_validate(row)
    o.has_embedding = has_embedding
    return o


# ----------------------------------------------------------------- analyze (async)
@router.post("/documents/{document_id}/vision", response_model=VisionJobOut, status_code=202)
def analyze_document(
    workspace_id: str, document_id: str, req: VisionProcessRequest = VisionProcessRequest(),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    runner=Depends(get_vision_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).create_or_get_job(owner_id, workspace_id, document_id, force=req.force))
    if job.status == "queued":
        runner.submit(job.id)
        db.refresh(job)
    return _job_out(job)


# ----------------------------------------------------------------- document-level status / analyses
@router.get("/documents/{document_id}/vision", response_model=VisionJobOut | None)
def vision_status(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).status_for_document(document_id, owner_id, workspace_id))
    return _job_out(job) if job else None


@router.get("/documents/{document_id}/vision/analyses", response_model=VisionAnalysisList)
def document_analyses(
    workspace_id: str, document_id: str, image_type: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    rows = _handle(lambda: _service(db).analyses(document_id, owner_id, workspace_id, image_type))
    return VisionAnalysisList(items=[_analysis_out(r, has) for r, has in rows], total=len(rows))


@router.get("/documents/{document_id}/vision/captions", response_model=list[CaptionOut])
def document_captions(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    rows = _handle(lambda: _service(db).analyses(document_id, owner_id, workspace_id))
    return [CaptionOut(asset_id=r.asset_id, asset_type=r.asset_type, image_type=r.image_type,
                       caption=r.caption, confidence=r.confidence) for r, _ in rows]


# ----------------------------------------------------------------- single analysis (image/diagram/chart/table details)
@router.get("/vision/analyses/{analysis_id}", response_model=VisionAnalysisOut)
def get_analysis(workspace_id: str, analysis_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    row, emb = _handle(lambda: _service(db).analysis(analysis_id, owner_id, workspace_id))
    return _analysis_out(row, emb is not None)


@router.get("/vision/analyses/{analysis_id}/embedding", response_model=VisionEmbeddingOut)
def get_embedding(
    workspace_id: str, analysis_id: str, include_vector: bool = Query(False),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    row, emb = _handle(lambda: _service(db).analysis(analysis_id, owner_id, workspace_id))
    if emb is None:
        raise HTTPException(status_code=404, detail="No vision embedding for this analysis.")
    out = VisionEmbeddingOut.model_validate(emb)
    if not include_vector:
        out.vector = None
    return out


@router.get("/vision/analyses/{analysis_id}/thumbnail")
def get_thumbnail(workspace_id: str, analysis_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    row, _emb = _handle(lambda: _service(db).analysis(analysis_id, owner_id, workspace_id))
    if not row.thumbnail_path or not os.path.exists(row.thumbnail_path):
        raise HTTPException(status_code=404, detail="No thumbnail available.")
    with open(row.thumbnail_path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type="image/png")


# ----------------------------------------------------------------- visual-knowledge search index
@router.get("/vision/search-meta", response_model=SearchMetaResponse)
def search_meta(
    workspace_id: str, keyword: str | None = Query(None), image_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    rows = _service(db).search_meta(workspace_id, keyword=keyword, image_type=image_type, limit=limit)
    return SearchMetaResponse(
        items=[SearchMetaItem(
            analysis_id=r.id, document_id=r.document_id, asset_type=r.asset_type, asset_id=r.asset_id,
            image_type=r.image_type, caption=r.caption, keywords=r.keywords or [], page_number=r.page_number,
            confidence=r.confidence) for r in rows],
        total=len(rows),
    )


# ----------------------------------------------------------------- job detail / retry / cancel
@router.get("/vision/job/{job_id}", response_model=VisionJobDetail)
def job_detail(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).get(job_id, owner_id))
    d = VisionJobDetail.model_validate(job)
    d.logs = job.logs or []
    return d


@router.post("/vision/job/{job_id}/retry", response_model=VisionJobOut)
def retry_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), runner=Depends(get_vision_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).retry(job_id, owner_id))
    runner.submit(job.id)
    db.refresh(job)
    return _job_out(job)


@router.post("/vision/job/{job_id}/cancel", response_model=VisionJobOut)
def cancel_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _job_out(_handle(lambda: _service(db).cancel(job_id, owner_id)))
