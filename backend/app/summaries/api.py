"""Summary HTTP routes — thin transport over SummaryService + a background runner.

Authenticated + workspace-scoped. Generation is asynchronous: create returns a `queued` summary
immediately and hands the id to the injected runner; the client polls `GET .../status`. The runner
and the engine are injected (lazily) so `app.summaries.api` imports with no faiss/torch and tests
substitute an inline runner + fake engine.
"""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.summaries.errors import SummaryError
from app.summaries.repository import SummaryRepository
from app.summaries.schemas import (
    SortField,
    SortOrder,
    StatusFilter,
    SummaryCitationOut,
    SummaryCreate,
    SummaryDetail,
    SummaryListResponse,
    SummaryOut,
    SummarySectionOut,
    SummaryUpdate,
)
from app.summaries.service import SummaryService
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/summaries", tags=["summaries"])

# Process-wide production runner (lazy singleton). Overridden in tests.
_runner = None


def get_summary_runner():
    global _runner
    if _runner is None:
        from app.summaries.runner import SummaryRunner
        _runner = SummaryRunner()
    return _runner


def _service(db: Session) -> SummaryService:
    return SummaryService(SummaryRepository(db), WorkspaceService(WorkspaceRepository(db)))


def _handle(fn):
    try:
        return fn()
    except SummaryError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _out(s) -> SummaryOut:
    return SummaryOut.model_validate(s)


def _detail(s, sections, cits) -> SummaryDetail:
    d = SummaryDetail.model_validate(s)
    d.sections = [
        SummarySectionOut(
            id=sec.id, heading=sec.heading, order=sec.order, content=sec.content,
            citation_count=sec.citation_count,
            citations=[SummaryCitationOut.model_validate(c) for c in cits.get(sec.id, [])],
        )
        for sec in sections
    ]
    return d


# ----------------------------------------------------------------- generate (async)
@router.post("", response_model=SummaryOut, status_code=202)
def generate_summary(
    workspace_id: str,
    req: SummaryCreate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    runner=Depends(get_summary_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    s = _handle(lambda: _service(db).create(
        owner_id, workspace_id,
        summary_type=req.summary_type, scope=req.scope,
        document_id=req.document_id, document_ids=req.document_ids, title=req.title,
    ))
    runner.submit(s.id)  # background (or inline in tests)
    db.refresh(s)        # reflect any inline-runner progress in the response
    return _out(s)


# ----------------------------------------------------------------- list
@router.get("", response_model=SummaryListResponse)
def list_summaries(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    summary_type: str | None = Query(None),
    status: StatusFilter = Query(StatusFilter.any),
    document_id: str | None = Query(None),
    sort_by: SortField = Query(SortField.created_at),
    order: SortOrder = Query(SortOrder.desc),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, total = _service(db).list(
        owner_id, workspace_id, page=page, page_size=page_size, search=search,
        summary_type=summary_type, status=status, document_id=document_id, sort_by=sort_by, order=order,
    )
    return SummaryListResponse(
        items=[_out(s) for s in items], total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


# ----------------------------------------------------------------- status (lightweight poll)
@router.get("/{summary_id}/status", response_model=SummaryOut)
def summary_status(workspace_id: str, summary_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _out(_handle(lambda: _service(db).get(summary_id, owner_id)))


# ----------------------------------------------------------------- details (with sections)
@router.get("/{summary_id}", response_model=SummaryDetail)
def get_summary(workspace_id: str, summary_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    s, sections, cits = _handle(lambda: _service(db).get_with_sections(summary_id, owner_id))
    return _detail(s, sections, cits)


# ----------------------------------------------------------------- export (markdown)
@router.get("/{summary_id}/export")
def export_summary(
    workspace_id: str,
    summary_id: str,
    format: str = Query("md", pattern="^(md|markdown|txt)$"),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    s, sections, cits = _handle(lambda: _service(db).get_with_sections(summary_id, owner_id))
    lines = [f"# {s.title}", ""]
    for sec in sections:
        lines.append(f"## {sec.heading}" if sec.heading else "")
        lines.append(sec.content)
        section_cits = cits.get(sec.id, [])
        if section_cits:
            lines.append("")
            lines.append("**Sources:**")
            for c in section_cits:
                page = f" p.{c.page_number}" if c.page_number else ""
                lines.append(f"- {c.citation_text[:200]}{page}")
        lines.append("")
    body = "\n".join(lines)
    safe = (s.title or "summary").replace('"', "").replace("/", "-")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


# ----------------------------------------------------------------- rename
@router.patch("/{summary_id}", response_model=SummaryOut)
def rename_summary(workspace_id: str, summary_id: str, req: SummaryUpdate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _out(_handle(lambda: _service(db).rename(summary_id, owner_id, req.title or "")))


# ----------------------------------------------------------------- regenerate / cancel / duplicate
@router.post("/{summary_id}/regenerate", response_model=SummaryOut)
def regenerate_summary(workspace_id: str, summary_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), runner=Depends(get_summary_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    s = _handle(lambda: _service(db).reset_for_regenerate(summary_id, owner_id))
    runner.submit(s.id)
    db.refresh(s)
    return _out(s)


@router.post("/{summary_id}/cancel", response_model=SummaryOut)
def cancel_summary(workspace_id: str, summary_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _out(_handle(lambda: _service(db).cancel(summary_id, owner_id)))


@router.post("/{summary_id}/duplicate", response_model=SummaryDetail, status_code=201)
def duplicate_summary(workspace_id: str, summary_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    copy = _handle(lambda: _service(db).duplicate(summary_id, owner_id))
    s, sections, cits = _service(db).get_with_sections(copy.id, owner_id)
    return _detail(s, sections, cits)


# ----------------------------------------------------------------- delete
@router.delete("/{summary_id}", status_code=204)
def delete_summary(
    workspace_id: str,
    summary_id: str,
    permanent: bool = Query(False),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete(summary_id, owner_id, permanent=permanent))
    return None
