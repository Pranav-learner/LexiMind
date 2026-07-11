"""Citation-intelligence HTTP routes — thin transport over CitationService.

Authenticated + workspace-scoped. Read-only intelligence over an index derived from Modules 4–7;
the index is refreshed transparently on read (see CitationService.ensure_synced). No AI runner is
needed — explanations are composed deterministically.
"""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.citations.errors import CitationError
from app.citations.repository import CitationRepository
from app.citations.schemas import (
    CitationDetail,
    CitationExplanation,
    CitationListResponse,
    CitationOut,
    CitationSortField,
    CitationStats,
    DocumentContext,
    ExplainFactor,
    RelatedCitation,
    RelatedKnowledge,
    ReferenceOut,
    ReferenceType,
    SortOrder,
)
from app.citations.service import CitationService
from app.db.base import get_db
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/citations", tags=["citations"])


def _service(db: Session) -> CitationService:
    return CitationService(CitationRepository(db))


def _handle(fn):
    try:
        return fn()
    except CitationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _out(c) -> CitationOut:
    return CitationOut.model_validate(c)


def _detail(c, refs, by_type, doc_ctx) -> CitationDetail:
    d = CitationDetail.model_validate(c)
    d.references = [ReferenceOut.model_validate(r) for r in refs]
    d.references_by_type = by_type
    d.document = DocumentContext(**doc_ctx)
    return d


# ----------------------------------------------------------------- search / list
@router.get("", response_model=CitationListResponse)
def search_citations(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    document_id: str | None = Query(None),
    page_number: int | None = Query(None),
    reference_type: ReferenceType | None = Query(None),
    min_confidence: float | None = Query(None, ge=0, le=1),
    sort_by: CitationSortField = Query(CitationSortField.reference_count),
    order: SortOrder = Query(SortOrder.desc),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, total = _service(db).search(
        workspace_id, owner_id, page=page, page_size=page_size, keyword=keyword,
        document_id=document_id, page_number=page_number, reference_type=reference_type,
        min_confidence=min_confidence, sort_by=sort_by, order=order,
    )
    return CitationListResponse(
        items=[_out(c) for c in items], total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


# ----------------------------------------------------------------- stats
@router.get("/stats", response_model=CitationStats)
def citation_stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    s = _service(db).stats(workspace_id, owner_id)
    s["most_referenced"] = [_out(c) for c in s["most_referenced"]]
    return CitationStats(**s)


# ----------------------------------------------------------------- reindex (manual)
@router.post("/reindex")
def reindex(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    count = _service(db).reindex(workspace_id, owner_id)
    return {"ok": True, "citations": count}


# ----------------------------------------------------------------- resolve from a chunk
@router.get("/by-chunk", response_model=CitationDetail)
def citation_by_chunk(
    workspace_id: str,
    document_id: str | None = Query(None),
    chunk_id: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    c, refs, by_type, doc_ctx = _handle(lambda: _service(db).by_chunk(workspace_id, owner_id, document_id, chunk_id))
    return _detail(c, refs, by_type, doc_ctx)


# ----------------------------------------------------------------- detail (panel)
@router.get("/{citation_id}", response_model=CitationDetail)
def citation_detail(workspace_id: str, citation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    c, refs, by_type, doc_ctx = _handle(lambda: _service(db).detail(citation_id, workspace_id, owner_id))
    return _detail(c, refs, by_type, doc_ctx)


# ----------------------------------------------------------------- related knowledge (explorer)
@router.get("/{citation_id}/related", response_model=RelatedKnowledge)
def related_knowledge(workspace_id: str, citation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    c, related, by_type, same_doc = _handle(lambda: _service(db).related(citation_id, workspace_id, owner_id))
    return RelatedKnowledge(
        citation_id=c.id,
        related=[RelatedCitation(**r) for r in related],
        references_by_type=by_type,
        same_document_citations=[_out(x) for x in same_doc],
    )


# ----------------------------------------------------------------- explain
@router.get("/{citation_id}/explain", response_model=CitationExplanation)
def explain_citation(workspace_id: str, citation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    data = _handle(lambda: _service(db).explain(citation_id, workspace_id, owner_id))
    return CitationExplanation(
        citation_id=data["citation_id"], summary=data["summary"],
        factors=[ExplainFactor(**f) for f in data["factors"]], retrieval_path=data["retrieval_path"],
    )
