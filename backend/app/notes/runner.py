"""Background note generation.

AI note generation is asynchronous: the API creates a `queued` row and hands the id to a runner
which processes it off the request path (large notes never block the UI). The client polls
`GET .../status`. Cancellation/retry are status transitions the worker observes.

Two runners implement the same `submit(note_id)` contract:
- `NoteRunner` (production): a `ThreadPoolExecutor` worker that opens its OWN DB session
  (`SessionLocal`) and runs `NoteService.generate_now` with the real `PipelineNotesEngine`.
- `InlineRunner` (tests): runs generation synchronously on submit with an injected session
  factory + fake engine, so the whole pipeline is exercised over HTTP without threads/faiss/LLM.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.notes.repository import NoteRepository
from app.notes.service import NoteService


class NoteRunner:
    def __init__(self, *, session_factory=None, engine: Any = None, max_workers: int = 2):
        self._session_factory = session_factory
        self._engine = engine
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="note")

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from app.db.base import SessionLocal
        return SessionLocal

    def _engine_impl(self):
        if self._engine is not None:
            return self._engine
        from app.notes.engine import PipelineNotesEngine
        return PipelineNotesEngine()

    def submit(self, note_id: str) -> None:
        self._pool.submit(self._run, note_id)

    def _run(self, note_id: str) -> None:
        Session = self._factory()
        db = Session()
        try:
            NoteService(NoteRepository(db)).generate_now(note_id, self._engine_impl())
        except Exception:
            db.rollback()
        finally:
            db.close()


class InlineRunner:
    """Synchronous runner: generation completes before `submit` returns (deterministic tests)."""

    def __init__(self, session_factory, engine: Any):
        self._session_factory = session_factory
        self._engine = engine

    def submit(self, note_id: str) -> None:
        db = self._session_factory()
        try:
            NoteService(NoteRepository(db)).generate_now(note_id, self._engine)
        finally:
            db.close()


class DeferredRunner:
    """No-op runner: leaves notes `queued` (used to test cancel/queue states)."""

    def submit(self, note_id: str) -> None:  # pragma: no cover - trivial
        return None
