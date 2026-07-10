"""Chat HTTP routes — thin transport over ChatService.

Authenticated + workspace-scoped. The heavy AI engine is injected via `get_chat_engine` (imported
lazily) so `app.chat.api` loads with no faiss/torch and tests can substitute a fake engine. The
message pipeline is exposed twice over the SAME service generator: a non-streaming JSON endpoint
and a streaming Server-Sent-Events endpoint.
"""

from __future__ import annotations

import json
from math import ceil
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.chat.errors import ChatError
from app.chat.repository import ConversationRepository, MessageRepository
from app.chat.schemas import (
    ArchivedFilter,
    CitationOut,
    ConversationCreate,
    ConversationListResponse,
    ConversationOut,
    ConversationUpdate,
    MessageListResponse,
    MessageOut,
    PinnedFilter,
    SendMessageRequest,
    SortField,
    SortOrder,
)
from app.chat.service import ChatService
from app.db.base import get_db
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/conversations", tags=["chat"])


# ----------------------------------------------------------------- dependencies
def get_chat_engine():
    """Return the production chat engine (reuses the AI pipeline). Overridden in tests."""
    from app.chat.engine import PipelineChatEngine

    return PipelineChatEngine()


def _service(db: Session) -> ChatService:
    return ChatService(
        ConversationRepository(db),
        MessageRepository(db),
        WorkspaceService(WorkspaceRepository(db)),
    )


def _handle(fn):
    try:
        return fn()
    except ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _conv_out(c) -> ConversationOut:
    return ConversationOut.model_validate(c)


def _msg_out(m, citations=()) -> MessageOut:
    out = MessageOut.model_validate(m)
    out.citations = [CitationOut.model_validate(c) for c in citations]
    return out


# ----------------------------------------------------------------- conversation CRUD
@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    workspace_id: str,
    req: ConversationCreate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    c = _handle(lambda: _service(db).create(
        owner_id, workspace_id,
        title=req.title, description=req.description, document_scope=req.document_scope,
        temperature=req.temperature, model_name=req.model_name,
    ))
    return _conv_out(c)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    archived: ArchivedFilter = Query(ArchivedFilter.active),
    pinned: PinnedFilter = Query(PinnedFilter.any),
    sort_by: SortField = Query(SortField.last_message_at),
    order: SortOrder = Query(SortOrder.desc),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, total = _service(db).list(
        owner_id, workspace_id, page=page, page_size=page_size, search=search,
        archived=archived, pinned=pinned, sort_by=sort_by, order=order,
    )
    return ConversationListResponse(
        items=[_conv_out(c) for c in items], total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


@router.get("/search", response_model=list[ConversationOut])
def search_conversations(
    workspace_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Broad search across titles, descriptions, message content, and citation text."""
    _verify_workspace(db, workspace_id, owner_id)
    return [_conv_out(c) for c in _service(db).search(owner_id, workspace_id, q, limit=limit)]


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    workspace_id: str,
    conversation_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).get(conversation_id, owner_id)))


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    workspace_id: str,
    conversation_id: str,
    req: ConversationUpdate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    c = _handle(lambda: _service(db).update(
        conversation_id, owner_id,
        title=req.title, description=req.description, document_scope=req.document_scope,
        temperature=req.temperature, model_name=req.model_name,
    ))
    return _conv_out(c)


@router.post("/{conversation_id}/pin", response_model=ConversationOut)
def pin_conversation(workspace_id: str, conversation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).set_pinned(conversation_id, owner_id, True)))


@router.post("/{conversation_id}/unpin", response_model=ConversationOut)
def unpin_conversation(workspace_id: str, conversation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).set_pinned(conversation_id, owner_id, False)))


@router.post("/{conversation_id}/archive", response_model=ConversationOut)
def archive_conversation(workspace_id: str, conversation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).archive(conversation_id, owner_id)))


@router.post("/{conversation_id}/restore", response_model=ConversationOut)
def restore_conversation(workspace_id: str, conversation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).restore(conversation_id, owner_id)))


@router.post("/{conversation_id}/duplicate", response_model=ConversationOut, status_code=201)
def duplicate_conversation(workspace_id: str, conversation_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _conv_out(_handle(lambda: _service(db).duplicate(conversation_id, owner_id)))


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    workspace_id: str,
    conversation_id: str,
    permanent: bool = Query(False, description="Hard-delete + purge messages instead of soft-delete."),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    _handle(lambda: _service(db).delete(conversation_id, owner_id, permanent=permanent))
    return None


# ----------------------------------------------------------------- messages: history
@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    workspace_id: str,
    conversation_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, cits, total = _handle(
        lambda: _service(db).list_messages(conversation_id, owner_id, page=page, page_size=page_size)
    )
    return MessageListResponse(
        items=[_msg_out(m, cits.get(m.id, [])) for m in items],
        total=total, page=page, page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


# ----------------------------------------------------------------- messages: send (non-streaming)
@router.post("/{conversation_id}/messages")
def send_message(
    workspace_id: str,
    conversation_id: str,
    req: SendMessageRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    engine=Depends(get_chat_engine),
):
    """Run one turn through the AI pipeline and return the persisted user + assistant messages."""
    _verify_workspace(db, workspace_id, owner_id)
    user_out = assistant_out = None
    ok = True
    try:
        for ev in _service(db).run_message(conversation_id, owner_id, req.content, engine, top_k=req.top_k):
            if ev["type"] == "user":
                user_out = _msg_out(ev["message"])
            elif ev["type"] == "done":
                assistant_out = _msg_out(ev["message"], ev.get("citations", []))
            elif ev["type"] == "error":
                assistant_out = _msg_out(ev["message"])
                ok = False
    except ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return {"ok": ok, "conversation_id": conversation_id, "user": user_out, "assistant": assistant_out}


# ----------------------------------------------------------------- messages: send (streaming SSE)
@router.post("/{conversation_id}/messages/stream")
def stream_message(
    workspace_id: str,
    conversation_id: str,
    req: SendMessageRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    engine=Depends(get_chat_engine),
):
    """Stream one turn as Server-Sent Events: `user` → `token`* → `done` (or `error`)."""
    _verify_workspace(db, workspace_id, owner_id)

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def _events() -> Iterator[str]:
        try:
            for ev in _service(db).run_message(conversation_id, owner_id, req.content, engine, top_k=req.top_k):
                t = ev["type"]
                if t == "token":
                    yield _sse("token", {"text": ev["text"]})
                elif t == "user":
                    yield _sse("user", _msg_out(ev["message"]).model_dump(mode="json"))
                elif t == "done":
                    yield _sse("done", _msg_out(ev["message"], ev.get("citations", [])).model_dump(mode="json"))
                elif t == "error":
                    yield _sse("error", {"message": _msg_out(ev["message"]).model_dump(mode="json"), "error": ev["error"]})
        except ChatError as e:
            yield _sse("error", {"error": str(e)})

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
