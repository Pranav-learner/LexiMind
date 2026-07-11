"""Multimodal context HTTP routes — thin transport over the context orchestrator.

Authenticated + workspace-scoped. Consumes Module-3 retrieval; the TEXT retriever is injected
(production = Phase-1 hybrid; tests = faiss-free lexical) so `app.mmcontext.api` imports with no
faiss/torch. One `build` endpoint exposes context preview + evidence ranking + compression report +
token budget + explanation; `prompt` is developer debug; `observability` feeds Phase-9.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.mmcontext.errors import ContextError
from app.mmcontext.schemas import ContextBuildRequest, ContextResponse, ObservabilityResponse
from app.mmcontext.service import MultimodalContextService
from app.mmretrieval.api import get_text_retriever
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/context", tags=["context"])


def _service(db: Session, text_retriever) -> MultimodalContextService:
    return MultimodalContextService(db, text_retriever=text_retriever)


def _handle(fn):
    try:
        return fn()
    except ContextError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- build (context preview + everything)
@router.post("/build", response_model=ContextResponse)
def build_context(
    workspace_id: str, req: ContextBuildRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    text_retriever=Depends(get_text_retriever),
):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db, text_retriever).build(owner_id, workspace_id, req))


# ----------------------------------------------------------------- prompt / developer debug
@router.post("/prompt")
def prompt_preview(
    workspace_id: str, req: ContextBuildRequest,
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    text_retriever=Depends(get_text_retriever),
):
    _verify_workspace(db, workspace_id, owner_id)
    req.developer = True
    result = _handle(lambda: _service(db, text_retriever).build(owner_id, workspace_id, req))
    return {"query": result["query"], "prompt": result["prompt"], "context": result["context"],
            "metrics": result["metrics"], "citations": result["citations"]}


# ----------------------------------------------------------------- observability (Phase-9)
@router.get("/observability", response_model=ObservabilityResponse)
def observability(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ObservabilityResponse(**_service(db, None).observability(workspace_id))
