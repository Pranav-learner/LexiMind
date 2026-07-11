"""Background multimodal processing.

Heavy OCR/vision/extraction must never block the API. The API creates a `queued` job and hands the
id to a runner which processes it off the request path. The client polls `GET .../status`.
Retry/cancel are status transitions the worker observes.

Two runners implement the same `submit(job_id)` contract:
- `IngestionRunner` (production): a `ThreadPoolExecutor` worker that opens its OWN DB session and
  runs `IngestionService.process_now` with the real `PipelineMultimodalEngine`.
- `InlineRunner` (tests): runs processing synchronously on submit with an injected session factory
  + fake engine, so the whole pipeline is exercised over HTTP without threads/OCR/vision libs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.ingestion.repository import IngestionRepository
from app.ingestion.service import IngestionService


class IngestionRunner:
    def __init__(self, *, session_factory=None, engine: Any = None, storage=None, max_workers: int = 2):
        self._session_factory = session_factory
        self._engine = engine
        self._storage = storage
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest")

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from app.db.base import SessionLocal
        return SessionLocal

    def _engine_impl(self):
        if self._engine is not None:
            return self._engine
        from app.ingestion.engines import PipelineMultimodalEngine
        return PipelineMultimodalEngine()

    def submit(self, job_id: str) -> None:
        self._pool.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        Session = self._factory()
        db = Session()
        try:
            IngestionService(IngestionRepository(db)).process_now(job_id, self._engine_impl(), self._storage)
        except Exception:
            db.rollback()
        finally:
            db.close()


class InlineRunner:
    """Synchronous runner: processing completes before `submit` returns (deterministic tests)."""

    def __init__(self, session_factory, engine: Any, storage=None):
        self._session_factory = session_factory
        self._engine = engine
        self._storage = storage

    def submit(self, job_id: str) -> None:
        db = self._session_factory()
        try:
            IngestionService(IngestionRepository(db)).process_now(job_id, self._engine, self._storage)
        finally:
            db.close()


class DeferredRunner:
    """No-op runner: leaves jobs `queued` (used to test cancel/queue states)."""

    def submit(self, job_id: str) -> None:  # pragma: no cover - trivial
        return None
