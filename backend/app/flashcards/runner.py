"""Background flashcard-deck generation.

AI generation is asynchronous: the API creates a `queued` deck and hands the id to a runner which
processes it off the request path (large batches never block the UI). The client polls
`GET .../status`. The target card count lives on the deck row (`target_count`), so the runner needs
only the id.

Two runners implement the same `submit(deck_id)` contract:
- `FlashcardRunner` (production): a `ThreadPoolExecutor` worker that opens its OWN DB session and
  runs `FlashcardService.generate_now` with the real `PipelineFlashcardEngine`.
- `InlineRunner` (tests): runs generation synchronously on submit with an injected session factory
  + fake engine, so the whole pipeline is exercised over HTTP without threads/faiss/LLM.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.flashcards.repository import FlashcardRepository
from app.flashcards.service import FlashcardService


def _service(db):
    """Build a service WITH workspace-counter maintenance (the runner keeps flashcard_count live)."""
    from app.workspaces.repository import WorkspaceRepository
    from app.workspaces.service import WorkspaceService
    return FlashcardService(FlashcardRepository(db), WorkspaceService(WorkspaceRepository(db)))


class FlashcardRunner:
    def __init__(self, *, session_factory=None, engine: Any = None, max_workers: int = 2):
        self._session_factory = session_factory
        self._engine = engine
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="flashcard")

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from app.db.base import SessionLocal
        return SessionLocal

    def _engine_impl(self):
        if self._engine is not None:
            return self._engine
        from app.flashcards.engine import PipelineFlashcardEngine
        return PipelineFlashcardEngine()

    def submit(self, deck_id: str) -> None:
        self._pool.submit(self._run, deck_id)

    def _run(self, deck_id: str) -> None:
        Session = self._factory()
        db = Session()
        try:
            deck = FlashcardRepository(db).get_deck_by_id_only(deck_id)
            count = deck.target_count if deck else 15
            _service(db).generate_now(deck_id, self._engine_impl(), count=count)
        except Exception:
            db.rollback()
        finally:
            db.close()


class InlineRunner:
    """Synchronous runner: generation completes before `submit` returns (deterministic tests)."""

    def __init__(self, session_factory, engine: Any):
        self._session_factory = session_factory
        self._engine = engine

    def submit(self, deck_id: str) -> None:
        db = self._session_factory()
        try:
            deck = FlashcardRepository(db).get_deck_by_id_only(deck_id)
            count = deck.target_count if deck else 15
            _service(db).generate_now(deck_id, self._engine, count=count)
        finally:
            db.close()


class DeferredRunner:
    """No-op runner: leaves decks `queued` (used to test cancel/queue states)."""

    def submit(self, deck_id: str) -> None:  # pragma: no cover - trivial
        return None
