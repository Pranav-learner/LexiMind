"""Knowledge Graph API (Step 14) — thin transport over KnowledgeGraphService.

Authenticated + workspace-scoped, mounted at `/workspaces/{id}/graph`. Build runs through an injected
runner (`get_graph_runner`) — a background threadpool in prod, a synchronous InlineRunner in tests
(overridden in conftest) — so uploads/reads never block on graph construction. Reads are direct.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.knowledge.errors import GraphError
from app.knowledge.repository import GraphRepository
from app.knowledge.schemas import (
    BuildRequest,
    EntityDetailOut,
    EntityOut,
    ExtractRequest,
    GraphLogDetailOut,
    GraphLogOut,
    GraphStatsOut,
    RelationshipOut,
    ValidationOut,
)
from app.knowledge.service import KnowledgeGraphService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/graph", tags=["knowledge-graph"])


# ----------------------------------------------------------------- injected background runner
_runner = None


def get_graph_runner():
    """Prod: a threadpool GraphRunner (lazy). Tests override this with a synchronous InlineRunner."""
    global _runner
    if _runner is None:
        from app.knowledge.runner import GraphRunner
        _runner = GraphRunner()
    return _runner


def _service(db: Session) -> KnowledgeGraphService:
    return KnowledgeGraphService(GraphRepository(db))


def _handle(fn):
    try:
        return fn()
    except GraphError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


# ----------------------------------------------------------------- build
@router.post("/build", response_model=GraphLogOut)
def build_workspace(workspace_id: str, req: BuildRequest = BuildRequest(),
                    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                    runner=Depends(get_graph_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    return GraphLogOut.model_validate(runner.submit(owner_id, workspace_id, scope="workspace"))


@router.post("/documents/{document_id}/build", response_model=GraphLogOut)
def build_document(workspace_id: str, document_id: str, req: BuildRequest = BuildRequest(),
                   owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
                   runner=Depends(get_graph_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    return GraphLogOut.model_validate(
        runner.submit(owner_id, workspace_id, scope="document", document_id=document_id))


@router.post("/extract", response_model=GraphLogDetailOut)
def extract_text(workspace_id: str, req: ExtractRequest, owner_id: str = Depends(get_current_user_id),
                 db: Session = Depends(get_db)):
    """Developer ad-hoc extraction from raw text (also the agent-contribution pathway)."""
    _verify_workspace(db, workspace_id, owner_id)
    ref = {"document_id": req.document_id, "chunk_id": None, "source_type": req.source_type}
    return GraphLogDetailOut.model_validate(_handle(lambda: _service(db).build_text(
        owner_id, workspace_id, req.text, source_ref=ref, scope="document" if req.document_id else "agent")))


# ----------------------------------------------------------------- entity / relationship search + details
@router.get("/entities", response_model=list[EntityOut])
def search_entities(workspace_id: str, query: str | None = Query(None), type: str | None = Query(None),
                    limit: int = Query(50, ge=1, le=200), owner_id: str = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [EntityOut(**e) for e in _service(db).search_entities(
        workspace_id, owner_id, query=query, entity_type=type, limit=limit)]


@router.get("/relationships", response_model=list[RelationshipOut])
def search_relationships(workspace_id: str, type: str | None = Query(None),
                         limit: int = Query(100, ge=1, le=500), owner_id: str = Depends(get_current_user_id),
                         db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [RelationshipOut(**r) for r in _service(db).search_relationships(
        workspace_id, owner_id, rel_type=type, limit=limit)]


@router.get("/stats", response_model=GraphStatsOut)
def stats(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return GraphStatsOut(**_service(db).stats(workspace_id))


@router.get("/validate", response_model=ValidationOut)
def validate(workspace_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return ValidationOut(**_service(db).validate(workspace_id, owner_id))


@router.get("/logs", response_model=list[GraphLogOut])
def logs(workspace_id: str, limit: int = Query(30, ge=1, le=100),
         owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return [GraphLogOut.model_validate(x) for x in _service(db).logs(workspace_id, owner_id, limit=limit)]


@router.get("/logs/{log_id}", response_model=GraphLogDetailOut)
def log_detail(workspace_id: str, log_id: str, owner_id: str = Depends(get_current_user_id),
               db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return GraphLogDetailOut.model_validate(_handle(lambda: _service(db).get_log(log_id, owner_id)))


@router.get("/entities/{entity_id}", response_model=EntityDetailOut)
def entity_detail(workspace_id: str, entity_id: str, owner_id: str = Depends(get_current_user_id),
                  db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return EntityDetailOut(**_handle(lambda: _service(db).entity_detail(entity_id, owner_id)))
