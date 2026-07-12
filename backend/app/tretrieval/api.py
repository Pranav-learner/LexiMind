"""Temporal retrieval & context HTTP routes — thin transport over the orchestrator (Step 12).

Authenticated + workspace-scoped. This module is an INSPECTABLE service (matching the mmcontext
precedent): it retrieves, assembles timeline-aware context, and BUILDS the timestamp-preserving prompt
— it does not call an LLM. `app.tretrieval.api` imports with no faiss/torch (retrievers are DB-backed;
the production cross-encoder reranker is lazy).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.tretrieval.errors import TemporalRetrievalError
from app.tretrieval.repository import TemporalRepository
from app.tretrieval.schemas import (
    ExplainResponse,
    PromptPreviewResponse,
    TemporalHealthResponse,
    TemporalSearchRequest,
    TemporalSearchResponse,
    TemporalStatsResponse,
)
from app.tretrieval.service import TemporalRetrievalService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/temporal", tags=["temporal-search"])


def _service(db: Session) -> TemporalRetrievalService:
    return TemporalRetrievalService(TemporalRepository(db))


def _handle(fn):
    try:
        return fn()
    except TemporalRetrievalError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- temporal search
@router.post("/search", response_model=TemporalSearchResponse)
def temporal_search(
    workspace_id: str, req: TemporalSearchRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).search(owner_id, workspace_id, req))


# ----------------------------------------------------------------- single-modality convenience routes
def _modality_search(db, owner_id, workspace_id, modality, q, top_k, document_id):
    req = TemporalSearchRequest(query=q, modalities=[modality], top_k=top_k, document_id=document_id,
                                build_context=False)
    return _service(db).search(owner_id, workspace_id, req)


@router.get("/timeline", response_model=TemporalSearchResponse)
def timeline_search(workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(15, ge=1, le=50),
                    document_id: str | None = Query(None), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _modality_search(db, owner_id, workspace_id, "event", q, top_k, document_id))


@router.get("/speakers", response_model=TemporalSearchResponse)
def speaker_search(workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50),
                   document_id: str | None = Query(None), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _modality_search(db, owner_id, workspace_id, "speaker", q, top_k, document_id))


@router.get("/chapters", response_model=TemporalSearchResponse)
def chapter_search(workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50),
                   document_id: str | None = Query(None), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _modality_search(db, owner_id, workspace_id, "chapter", q, top_k, document_id))


@router.get("/scenes", response_model=TemporalSearchResponse)
def scene_search(workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50),
                 document_id: str | None = Query(None), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _modality_search(db, owner_id, workspace_id, "scene", q, top_k, document_id))


@router.get("/events", response_model=TemporalSearchResponse)
def event_search(workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(15, ge=1, le=50),
                 document_id: str | None = Query(None), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _modality_search(db, owner_id, workspace_id, "event", q, top_k, document_id))


# ----------------------------------------------------------------- prompt preview / explanation
@router.post("/prompt", response_model=PromptPreviewResponse)
def prompt_preview(workspace_id: str, req: TemporalSearchRequest, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).prompt_preview(owner_id, workspace_id, req))


@router.post("/explain", response_model=ExplainResponse)
def explain(workspace_id: str, req: TemporalSearchRequest, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).explain(owner_id, workspace_id, req))


# ----------------------------------------------------------------- stats / health
@router.get("/stats", response_model=TemporalStatsResponse)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TemporalStatsResponse(**_service(db).stats(workspace_id))


@router.get("/health", response_model=TemporalHealthResponse)
def health(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TemporalHealthResponse(**_service(db).health(workspace_id))
