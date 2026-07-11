"""Multimodal search HTTP routes — thin transport over the retrieval orchestrator.

Authenticated + workspace-scoped. The TEXT retriever is injected (production wraps the Phase-1 hybrid
pipeline; tests inject the faiss-free lexical one) so `app.mmretrieval.api` imports with no faiss/torch.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.mmretrieval.errors import RetrievalError
from app.mmretrieval.repository import RetrievalRepository
from app.mmretrieval.schemas import (
    HealthResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
    SuggestionsResponse,
)
from app.mmretrieval.service import MultimodalRetrievalService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["search"])

_text_retriever = None


def get_text_retriever():
    """Production text retriever = the Phase-1 hybrid pipeline (lazy). Overridden to the lexical
    (faiss-free) retriever in tests."""
    global _text_retriever
    if _text_retriever is None:
        from app.mmretrieval.retrievers import HybridTextRetriever
        _text_retriever = HybridTextRetriever()
    return _text_retriever


def _service(db: Session, text_retriever) -> MultimodalRetrievalService:
    return MultimodalRetrievalService(RetrievalRepository(db), text_retriever=text_retriever)


def _handle(fn):
    try:
        return fn()
    except RetrievalError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- multimodal search
@router.post("/search", response_model=SearchResponse)
def search(
    workspace_id: str, req: SearchRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    text_retriever=Depends(get_text_retriever),
):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db, text_retriever).search(owner_id, workspace_id, req))


# ----------------------------------------------------------------- search by a single modality
@router.get("/search/modality/{modality}", response_model=SearchResponse)
def search_modality(
    workspace_id: str, modality: str, q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50),
    document_id: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    text_retriever=Depends(get_text_retriever),
):
    _verify_workspace(db, workspace_id, owner_id)
    req = SearchRequest(query=q, modalities=[modality], top_k=top_k, document_id=document_id)
    return _handle(lambda: _service(db, text_retriever).search(owner_id, workspace_id, req))


# ----------------------------------------------------------------- suggestions
@router.get("/search/suggestions", response_model=SuggestionsResponse)
def suggestions(workspace_id: str, q: str = Query("", max_length=200), owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    items = _service(db, None).suggestions(workspace_id, owner_id, q)
    return SuggestionsResponse(query=q, suggestions=items)


# ----------------------------------------------------------------- statistics
@router.get("/search/stats", response_model=StatsResponse)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return StatsResponse(**_service(db, None).stats(workspace_id))


# ----------------------------------------------------------------- health / monitoring
@router.get("/search/health", response_model=HealthResponse)
def health(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), text_retriever=Depends(get_text_retriever)):
    _verify_workspace(db, workspace_id, owner_id)
    return HealthResponse(**_service(db, text_retriever).health(workspace_id))
