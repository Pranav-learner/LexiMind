"""Note HTTP routes — thin transport over NoteService + a background runner.

Authenticated + workspace-scoped. Manual notes (blank/selection/chat/summary) are created
synchronously; AI generation is asynchronous (create returns a `queued` note and the client polls
`GET .../status`). Both the generation runner and the assist engine are injected (lazily) so
`app.notes.api` imports with no faiss/torch and tests substitute inline/fake implementations.

Two routers are exported:
- `router`     — /workspaces/{id}/notes/...   (notes CRUD, generate, autosave, assist, export)
- `tag_router` — /workspaces/{id}/tags/...     (tag management)
"""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.notes.errors import NoteError
from app.notes.repository import NoteRepository
from app.notes.schemas import (
    ArchivedFilter,
    AssistRequest,
    AssistResponse,
    NoteContentUpdate,
    NoteCreate,
    NoteDetail,
    NoteGenerate,
    NoteListResponse,
    NoteMetaUpdate,
    NoteOut,
    NoteSectionOut,
    NoteCitationOut,
    NoteTagsUpdate,
    OutlineItem,
    PinnedFilter,
    SortField,
    SortOrder,
    StatusFilter,
    TagCreate,
    TagListResponse,
    TagOut,
    TagUpdate,
)
from app.notes.service import NoteService
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/notes", tags=["notes"])
tag_router = APIRouter(prefix="/workspaces/{workspace_id}/tags", tags=["tags"])

# Process-wide production singletons (lazy). Overridden in tests.
_runner = None
_engine = None


def get_notes_runner():
    global _runner
    if _runner is None:
        from app.notes.runner import NoteRunner
        _runner = NoteRunner()
    return _runner


def get_notes_engine():
    global _engine
    if _engine is None:
        from app.notes.engine import PipelineNotesEngine
        _engine = PipelineNotesEngine()
    return _engine


def _service(db: Session) -> NoteService:
    return NoteService(NoteRepository(db), WorkspaceService(WorkspaceRepository(db)))


def _handle(fn):
    try:
        return fn()
    except NoteError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _tag_out(t) -> TagOut:
    return TagOut.model_validate(t)


def _out(note, tags=None) -> NoteOut:
    o = NoteOut.model_validate(note)
    o.tags = [_tag_out(t) for t in (tags or [])]
    return o


def _detail(note, sections, citations, tags, outline) -> NoteDetail:
    d = NoteDetail.model_validate(note)
    d.tags = [_tag_out(t) for t in tags]
    d.sections = [NoteSectionOut.model_validate(s) for s in sections]
    d.citations = [NoteCitationOut.model_validate(c) for c in citations]
    d.outline = [OutlineItem(**item) for item in outline]
    return d


# ============================================================ notes: create (manual, sync)
@router.post("", response_model=NoteDetail, status_code=201)
def create_note(
    workspace_id: str,
    req: NoteCreate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    note = _handle(lambda: _service(db).create(
        owner_id, workspace_id,
        title=req.title, description=req.description, content=req.content,
        source=req.source, document_id=req.document_id, conversation_id=req.conversation_id,
        tags=req.tags,
        citations=[c.model_dump() for c in req.citations] if req.citations else None,
    ))
    n, sections, citations, tags, outline = _service(db).get_detail(note.id, owner_id, touch=False)
    return _detail(n, sections, citations, tags, outline)


# ============================================================ notes: generate (AI, async)
@router.post("/generate", response_model=NoteOut, status_code=202)
def generate_note(
    workspace_id: str,
    req: NoteGenerate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    runner=Depends(get_notes_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    note = _handle(lambda: _service(db).create_generated(
        owner_id, workspace_id,
        note_type=req.note_type, scope=req.scope, document_id=req.document_id,
        document_ids=req.document_ids, conversation_id=req.conversation_id,
        title=req.title, subject=req.subject,
    ))
    runner.submit(note.id)  # background (or inline in tests)
    db.refresh(note)
    return _out(note)


# ============================================================ notes: conversions
@router.post("/from-summary/{summary_id}", response_model=NoteDetail, status_code=201)
def note_from_summary(
    workspace_id: str, summary_id: str,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    note = _handle(lambda: _service(db).convert_from_summary(owner_id, workspace_id, summary_id))
    n, sections, citations, tags, outline = _service(db).get_detail(note.id, owner_id, touch=False)
    return _detail(n, sections, citations, tags, outline)


@router.post("/from-message/{message_id}", response_model=NoteDetail, status_code=201)
def note_from_message(
    workspace_id: str, message_id: str,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    note = _handle(lambda: _service(db).convert_from_message(owner_id, workspace_id, message_id))
    n, sections, citations, tags, outline = _service(db).get_detail(note.id, owner_id, touch=False)
    return _detail(n, sections, citations, tags, outline)


# ============================================================ notes: list
@router.get("", response_model=NoteListResponse)
def list_notes(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    note_type: str | None = Query(None),
    source: str | None = Query(None),
    document_id: str | None = Query(None),
    conversation_id: str | None = Query(None),
    tag_id: str | None = Query(None),
    status: StatusFilter = Query(StatusFilter.any),
    archived: ArchivedFilter = Query(ArchivedFilter.active),
    pinned: PinnedFilter = Query(PinnedFilter.any),
    sort_by: SortField = Query(SortField.updated_at),
    order: SortOrder = Query(SortOrder.desc),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, total, tag_map = _service(db).list(
        owner_id, workspace_id, page=page, page_size=page_size, search=search,
        note_type=note_type, source=source, document_id=document_id,
        conversation_id=conversation_id, tag_id=tag_id, status=status, archived=archived,
        pinned=pinned, sort_by=sort_by, order=order,
    )
    return NoteListResponse(
        items=[_out(n, tag_map.get(n.id, [])) for n in items],
        total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


# ============================================================ notes: status (lightweight poll)
@router.get("/{note_id}/status", response_model=NoteOut)
def note_status(workspace_id: str, note_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _out(_handle(lambda: _service(db).get(note_id, owner_id)))


# ============================================================ notes: detail
@router.get("/{note_id}", response_model=NoteDetail)
def get_note(workspace_id: str, note_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    n, sections, citations, tags, outline = _handle(lambda: _service(db).get_detail(note_id, owner_id))
    return _detail(n, sections, citations, tags, outline)


# ============================================================ notes: autosave (content)
@router.put("/{note_id}/content", response_model=NoteOut)
def save_note_content(
    workspace_id: str, note_id: str, req: NoteContentUpdate,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    n = _handle(lambda: _service(db).save_content(
        note_id, owner_id, content=req.content, base_version=req.base_version, title=req.title,
    ))
    return _out(n)


# ============================================================ notes: AI-assisted editing (sync)
@router.post("/{note_id}/assist", response_model=AssistResponse)
def assist_note(
    workspace_id: str, note_id: str, req: AssistRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    engine=Depends(get_notes_engine),
):
    _verify_workspace(db, workspace_id, owner_id)
    from app.services.answer_service import NOTE_ASSIST_OPS  # lightweight; keeps module import faiss-free
    if req.operation not in NOTE_ASSIST_OPS:
        raise HTTPException(status_code=422, detail=f"Unknown assist operation '{req.operation}'.")
    result = _handle(lambda: _service(db).assist(
        note_id, owner_id, engine, operation=req.operation, selection=req.selection,
        instruction=req.instruction, ground=req.ground,
    ))
    return AssistResponse(operation=req.operation, result=result)


# ============================================================ notes: metadata patch
@router.patch("/{note_id}", response_model=NoteOut)
def update_note(
    workspace_id: str, note_id: str, req: NoteMetaUpdate,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    n = _handle(lambda: _service(db).update_meta(
        note_id, owner_id, title=req.title, description=req.description,
        is_pinned=req.is_pinned, is_favorite=req.is_favorite, is_archived=req.is_archived,
    ))
    return _out(n, _service(db).repo.tags_for([n.id]).get(n.id, []))


# ============================================================ notes: tags on a note
@router.put("/{note_id}/tags", response_model=NoteOut)
def set_note_tags(
    workspace_id: str, note_id: str, req: NoteTagsUpdate,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    n = _handle(lambda: _service(db).set_note_tags(note_id, owner_id, req.tag_ids))
    return _out(n, _service(db).repo.tags_for([n.id]).get(n.id, []))


# ============================================================ notes: regenerate / cancel / duplicate
@router.post("/{note_id}/regenerate", response_model=NoteOut)
def regenerate_note(workspace_id: str, note_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), runner=Depends(get_notes_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    n = _handle(lambda: _service(db).reset_for_regenerate(note_id, owner_id))
    runner.submit(n.id)
    db.refresh(n)
    return _out(n)


@router.post("/{note_id}/cancel", response_model=NoteOut)
def cancel_note(workspace_id: str, note_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _out(_handle(lambda: _service(db).cancel(note_id, owner_id)))


@router.post("/{note_id}/duplicate", response_model=NoteDetail, status_code=201)
def duplicate_note(workspace_id: str, note_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    copy = _handle(lambda: _service(db).duplicate(note_id, owner_id))
    n, sections, citations, tags, outline = _service(db).get_detail(copy.id, owner_id, touch=False)
    return _detail(n, sections, citations, tags, outline)


# ============================================================ notes: export (markdown)
@router.get("/{note_id}/export")
def export_note(
    workspace_id: str, note_id: str,
    format: str = Query("md", pattern="^(md|markdown|txt)$"),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    n, _sections, citations, _tags, _outline = _handle(lambda: _service(db).get_detail(note_id, owner_id, touch=False))
    lines = [f"# {n.title}", ""]
    if n.description:
        lines += [f"> {n.description}", ""]
    lines.append(n.content)
    if citations:
        lines += ["", "---", "", "## Sources", ""]
        for c in citations:
            page = f" (p.{c.page_number})" if c.page_number else ""
            lines.append(f"- {c.citation_text[:200]}{page}")
    body = "\n".join(lines)
    safe = (n.title or "note").replace('"', "").replace("/", "-")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


# ============================================================ notes: delete
@router.delete("/{note_id}", status_code=204)
def delete_note(
    workspace_id: str, note_id: str,
    permanent: bool = Query(False),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete(note_id, owner_id, permanent=permanent))
    return None


# ============================================================ tags: CRUD
@tag_router.get("", response_model=TagListResponse)
def list_tags(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    tags = _service(db).list_tags(owner_id, workspace_id)
    return TagListResponse(items=[_tag_out(t) for t in tags], total=len(tags))


@tag_router.post("", response_model=TagOut, status_code=201)
def create_tag(workspace_id: str, req: TagCreate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _tag_out(_handle(lambda: _service(db).create_tag(owner_id, workspace_id, name=req.name, color=req.color)))


@tag_router.patch("/{tag_id}", response_model=TagOut)
def update_tag(workspace_id: str, tag_id: str, req: TagUpdate, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _tag_out(_handle(lambda: _service(db).update_tag(tag_id, owner_id, name=req.name, color=req.color)))


@tag_router.delete("/{tag_id}", status_code=204)
def delete_tag(workspace_id: str, tag_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete_tag(tag_id, owner_id))
    return None
