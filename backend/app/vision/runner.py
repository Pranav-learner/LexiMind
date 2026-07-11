"""Background vision processing.

Vision-language inference (captioning, classification, CLIP embeddings) is heavy and must never
block the API. The API creates a `queued` job and hands the id to a runner which processes it off
the request path. The client polls `GET .../vision`. Retry/cancel are status transitions.

Two runners implement `submit(job_id)`:
- `VisionRunner` (production): a `ThreadPoolExecutor` worker with its OWN DB session + the real
  `PipelineVisionEngine`.
- `InlineRunner` (tests): runs synchronously with an injected session factory + fake engine.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.vision.repository import VisionRepository
from app.vision.service import VisionService


class VisionRunner:
    def __init__(self, *, session_factory=None, engine: Any = None, max_workers: int = 2):
        self._session_factory = session_factory
        self._engine = engine
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vision")

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from app.db.base import SessionLocal
        return SessionLocal

    def _engine_impl(self):
        if self._engine is not None:
            return self._engine
        from app.vision.engines import PipelineVisionEngine
        return PipelineVisionEngine()

    def submit(self, job_id: str) -> None:
        self._pool.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        Session = self._factory()
        db = Session()
        try:
            VisionService(VisionRepository(db)).process_now(job_id, self._engine_impl())
        except Exception:
            db.rollback()
        finally:
            db.close()


class InlineRunner:
    """Synchronous runner: analysis completes before `submit` returns (deterministic tests)."""

    def __init__(self, session_factory, engine: Any):
        self._session_factory = session_factory
        self._engine = engine

    def submit(self, job_id: str) -> None:
        db = self._session_factory()
        try:
            VisionService(VisionRepository(db)).process_now(job_id, self._engine)
        finally:
            db.close()


class DeferredRunner:
    """No-op runner: leaves jobs `queued` (used to test cancel/queue states)."""

    def submit(self, job_id: str) -> None:  # pragma: no cover - trivial
        return None
