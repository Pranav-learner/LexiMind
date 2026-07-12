"""Interactive Knowledge Workspace API (Step 14) — thin transport over the orchestrator.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/knowledge-workspace`. AI Graph Chat
reuses the injected chat engine (`get_graph_chat_engine`, overridden in tests with a faked answer) and
the UNCHANGED ChatService → single AnswerService pathway. Consistent with the Phase-4/5 workspace APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.knowledgeworkspace.errors import WorkspaceError
from app.knowledgeworkspace.schemas import (
    EditRequest,
    GraphChatRequest,
    GraphChatResponse,
    SearchRequest,
)
from app.knowledgeworkspace.service import KnowledgeWorkspaceOrchestrator
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/knowledge-workspace", tags=["knowledge-workspace"])


def get_graph_chat_engine():
    """Prod: GraphChatEngine (answer_service.complete). Tests override with a faked answer_fn."""
    from app.knowledgeworkspace.engine import GraphChatEngine
    return GraphChatEngine()


def _orch(db: Session) -> KnowledgeWorkspaceOrchestrator:
    return KnowledgeWorkspaceOrchestrator(db)


def _handle(fn):
    try:
        return fn()
    except WorkspaceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- overview + graph explorer
@router.get("/overview", response_model=dict)
def overview(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _orch(db).overview(workspace_id, owner_id)


@router.get("/graph", response_model=dict)
def graph_view(workspace_id: str, seed: str | None = Query(None), hops: int = Query(1, ge=1, le=3),
               limit: int = Query(40, ge=1, le=200), owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _orch(db).graph_view(workspace_id, owner_id, seed=seed, hops=hops, limit=limit))


@router.get("/entities/{entity_id}", response_model=dict)
def entity_detail(workspace_id: str, entity_id: str, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _orch(db).entity_detail(workspace_id, owner_id, entity_id))


@router.get("/relationships/{rel_id}", response_model=dict)
def relationship_detail(workspace_id: str, rel_id: str, owner_id: str = Depends(get_current_user_id),
                        db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _orch(db).relationship_detail(workspace_id, owner_id, rel_id))


# ----------------------------------------------------------------- search / timeline / analytics / activity
@router.post("/search", response_model=dict)
def search(workspace_id: str, req: SearchRequest, owner_id: str = Depends(get_current_user_id),
           db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _orch(db).search(workspace_id, owner_id, query=req.query, hybrid=req.hybrid)


@router.get("/timeline", response_model=list)
def timeline(workspace_id: str, limit: int = Query(60, ge=1, le=200),
             owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _orch(db).timeline(workspace_id, owner_id, limit=limit)


@router.get("/analytics", response_model=dict)
def analytics(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _orch(db).analytics(workspace_id, owner_id)


@router.get("/activity", response_model=list)
def activity(workspace_id: str, limit: int = Query(50, ge=1, le=200),
             owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _orch(db).activity(workspace_id, owner_id, limit=limit)


# ----------------------------------------------------------------- AI graph chat (reuses ChatService)
@router.post("/chat", response_model=GraphChatResponse)
def graph_chat(workspace_id: str, req: GraphChatRequest, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db), engine=Depends(get_graph_chat_engine)):
    _verify_workspace(db, workspace_id, owner_id)
    return GraphChatResponse(**_handle(lambda: _orch(db).graph_chat(
        owner_id, workspace_id, content=req.content, engine=engine,
        conversation_id=req.conversation_id, top_k=req.top_k)))


# ----------------------------------------------------------------- controlled editing
@router.post("/edit", response_model=dict)
def edit(workspace_id: str, req: EditRequest, owner_id: str = Depends(get_current_user_id),
         db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _orch(db).edit(workspace_id, owner_id, op=req.op, params=req.params))
