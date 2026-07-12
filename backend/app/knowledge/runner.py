"""Background graph-construction runner (Step 11) — never blocks uploads; supports retries.

Mirrors the ingestion/media/vision runner pattern: a threadpool `GraphRunner` for production (build off
the request path) + an `InlineRunner` for tests (synchronous, deterministic). Both own their DB session,
build the graph incrementally, and persist the `GraphConstructionLog`. The prod runner writes a `queued`
log first (so the client can poll) and updates it to `completed`/`failed` when the build finishes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.knowledge.models import GraphConstructionLog
from app.knowledge.repository import GraphRepository, new_id
from app.knowledge.service import KnowledgeGraphService


def _build(db, owner_id: str, workspace_id: str, scope: str, document_id: Optional[str],
           log_id: Optional[str]) -> GraphConstructionLog:
    svc = KnowledgeGraphService(GraphRepository(db))
    if scope == "workspace":
        return svc.build_workspace(owner_id, workspace_id, log_id=log_id)
    return svc.build_document(owner_id, workspace_id, document_id, log_id=log_id)


class GraphRunner:
    def __init__(self, *, session_factory=None, max_workers: int = 2):
        self._factory = session_factory
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="graph")

    def _session(self):
        if self._factory is not None:
            return self._factory()
        from app.db.base import SessionLocal
        return SessionLocal()

    def submit(self, owner_id: str, workspace_id: str, *, scope: str,
               document_id: Optional[str] = None) -> GraphConstructionLog:
        # write a queued placeholder so the client can poll, then build in the background
        db = self._session()
        try:
            queued = GraphConstructionLog(id=new_id("gcl"), workspace_id=workspace_id, owner_id=owner_id,
                                          document_id=document_id, scope=scope, status="queued")
            GraphRepository(db).save_log(queued)
            log_id = queued.id
        finally:
            db.close()
        self._pool.submit(self._run, owner_id, workspace_id, scope, document_id, log_id)
        return queued

    def _run(self, owner_id, workspace_id, scope, document_id, log_id) -> None:
        db = self._session()
        try:
            _build(db, owner_id, workspace_id, scope, document_id, log_id)
        except Exception:
            try:
                log = GraphRepository(db).get_log(log_id, owner_id)
                if log is not None:
                    log.status = "failed"; db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()


class InlineRunner:
    """Synchronous runner for tests — builds immediately and returns the completed log."""

    def __init__(self, session_factory):
        self._factory = session_factory

    def submit(self, owner_id: str, workspace_id: str, *, scope: str,
               document_id: Optional[str] = None) -> GraphConstructionLog:
        db = self._factory()
        try:
            return _build(db, owner_id, workspace_id, scope, document_id, None)
        finally:
            db.close()


class DeferredRunner:
    def submit(self, *a: Any, **k: Any) -> None:  # pragma: no cover - leaves the graph unbuilt
        return None
