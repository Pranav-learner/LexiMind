"""Media AI Workspace HTTP routes — thin transport over the orchestrator (Step 16).

Authenticated + workspace-scoped. The media chat engine (TemporalChatEngine) + the knowledge-asset
runners are injected via Depends so tests substitute a faked answer function + inline runners, and
`app.mediaworkspace.api` imports with no faiss/torch/LLM. Consistent with the mmworkspace + chat APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.mediaworkspace.errors import MediaWorkspaceError
from app.mediaworkspace.schemas import (
    AiActionRequest,
    AiActionResponse,
    InteractionRequest,
    MediaChatRequest,
    MediaChatResponse,
    MediaLibraryResponse,
    MediaSearchResponse,
    ObservabilityResponse,
    OverviewResponse,
    PlaybackMetaResponse,
    TimelineResponse,
)
from app.mediaworkspace.service import MediaWorkspaceOrchestrator
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/media-ai", tags=["media-ai-workspace"])


# ----------------------------------------------------------------- injected dependencies
def get_temporal_chat_engine():
    """Production media chat engine (temporal retrieval → prompt → answer_service). Overridden in tests
    with a faked answer function so no LLM/ollama runs."""
    from app.mediaworkspace.engine import TemporalChatEngine
    return TemporalChatEngine()


def get_summary_runner():
    from app.summaries.runner import SummaryRunner
    return SummaryRunner()


def get_notes_runner():
    from app.notes.runner import NoteRunner
    return NoteRunner()


def get_flashcards_runner():
    from app.flashcards.runner import FlashcardRunner
    return FlashcardRunner()


def _orch(db: Session) -> MediaWorkspaceOrchestrator:
    return MediaWorkspaceOrchestrator(db)


def _handle(fn):
    try:
        return fn()
    except MediaWorkspaceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- overview / library
@router.get("/overview", response_model=OverviewResponse)
def overview(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return OverviewResponse(**_orch(db).overview(workspace_id, owner_id))


@router.get("/library", response_model=MediaLibraryResponse)
def library(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return MediaLibraryResponse(**_orch(db).library(workspace_id, owner_id))


# ----------------------------------------------------------------- timeline / playback
@router.get("/{document_id}/timeline", response_model=TimelineResponse)
def timeline(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return TimelineResponse(**_handle(lambda: _orch(db).unified_timeline(workspace_id, owner_id, document_id)))


@router.get("/{document_id}/playback", response_model=PlaybackMetaResponse)
def playback(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return PlaybackMetaResponse(**_handle(lambda: _orch(db).playback_meta(workspace_id, owner_id, document_id)))


# ----------------------------------------------------------------- media AI chat
@router.post("/chat", response_model=MediaChatResponse)
def media_chat(
    workspace_id: str, req: MediaChatRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    engine=Depends(get_temporal_chat_engine),
):
    _verify_workspace(db, workspace_id, owner_id)
    result = _handle(lambda: _orch(db).media_chat(
        owner_id, workspace_id, content=req.content, engine=engine,
        conversation_id=req.conversation_id, document_id=req.document_id, top_k=req.top_k))
    return MediaChatResponse(**result)


# ----------------------------------------------------------------- knowledge-asset AI actions
@router.post("/action", response_model=AiActionResponse)
def ai_action(
    workspace_id: str, req: AiActionRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    summary_runner=Depends(get_summary_runner), notes_runner=Depends(get_notes_runner),
    flashcard_runner=Depends(get_flashcards_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    result = _handle(lambda: _orch(db).ai_action(
        workspace_id, owner_id, req.action, req.document_id, focus=req.focus, count=req.count,
        summary_runner=summary_runner, notes_runner=notes_runner, flashcard_runner=flashcard_runner))
    return AiActionResponse(**result)


# ----------------------------------------------------------------- unified media search
@router.get("/search", response_model=MediaSearchResponse)
def search(
    workspace_id: str, q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50),
    document_id: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    return MediaSearchResponse(**_orch(db).search(owner_id, workspace_id, q, top_k=top_k, document_id=document_id))


# ----------------------------------------------------------------- observability (Step 15)
@router.post("/interactions", status_code=201)
def record_interaction(workspace_id: str, req: InteractionRequest, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    ev = _orch(db).record_interaction(owner_id, workspace_id, event_type=req.event_type,
                                      document_id=req.document_id, target=req.target,
                                      position_ms=req.position_ms, meta=req.meta)
    return {"id": ev.id, "recorded": True}


@router.get("/observability", response_model=ObservabilityResponse)
def observability(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ObservabilityResponse(**_orch(db).observability(workspace_id))
