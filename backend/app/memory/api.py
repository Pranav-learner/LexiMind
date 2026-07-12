"""Semantic Memory & Graph Retrieval API (Step 13) — thin transport over SemanticMemoryService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/memory`. Retrieval is LLM-free; the
`hybrid` mode reuses the Phase-4 unified retrieval as the vector provider and the Phase-4 fusion — the
graph is just another modality. Consistent with the graph/verification/orchestration developer APIs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.memory.errors import MemoryError
from app.memory.schemas import (
    MemoryRetrieveRequest,
    RecognizeRequest,
    SemanticMemoryLogOut,
    SyncRequest,
)
from app.memory.service import MemorySynchronizer, SemanticMemoryService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/memory", tags=["semantic-memory"])


def _service(db: Session) -> SemanticMemoryService:
    return SemanticMemoryService(db)


def _handle(fn):
    try:
        return fn()
    except MemoryError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- retrieval
@router.post("/retrieve", response_model=dict)
def retrieve(workspace_id: str, req: MemoryRetrieveRequest, owner_id: str = Depends(get_current_user_id),
             db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).retrieve(workspace_id, owner_id, query=req.query, hops=req.hops,
                                 strategy=req.strategy, rel_types=req.rel_types, max_nodes=req.max_nodes,
                                 limit=req.limit, hybrid=req.hybrid, seed_entity_ids=req.seed_entity_ids)


@router.post("/recognize", response_model=list[dict])
def recognize(workspace_id: str, req: RecognizeRequest, owner_id: str = Depends(get_current_user_id),
              db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).recognize(workspace_id, owner_id, req.query)


@router.get("/entities/{entity_id}/neighborhood", response_model=dict)
def neighborhood(workspace_id: str, entity_id: str, hops: int = Query(1, ge=1, le=4),
                 strategy: str = Query("bfs", pattern="^(bfs|dfs)$"), max_nodes: int = Query(40, ge=1, le=200),
                 owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _handle(lambda: _service(db).neighborhood(workspace_id, owner_id, entity_id, hops=hops,
                                                     strategy=strategy, max_nodes=max_nodes))


# ----------------------------------------------------------------- sync / stats / logs
@router.post("/sync", response_model=dict)
def sync(workspace_id: str, req: SyncRequest, owner_id: str = Depends(get_current_user_id),
         db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return MemorySynchronizer(db).sync(owner_id, workspace_id, document_id=req.document_id, force=req.force)


@router.get("/stats", response_model=dict)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _service(db).stats(workspace_id)


@router.get("/logs", response_model=list[SemanticMemoryLogOut])
def logs(workspace_id: str, limit: int = Query(30, ge=1, le=100),
         owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [SemanticMemoryLogOut.model_validate(x) for x in _service(db).logs(workspace_id, owner_id, limit=limit)]
