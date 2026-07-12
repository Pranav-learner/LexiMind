"""SQLAlchemy engine, session factory, and declarative base.

Design notes:
- One process-wide engine, created from `settings.database_url`. For SQLite we pass
  `check_same_thread=False` because FastAPI serves requests from a threadpool and the
  connection may be touched by a different thread than the one that created it.
- `SessionLocal` is a plain session factory. Request handlers get a session via the
  `get_db` FastAPI dependency (opened per-request, always closed). Scripts/tests use the
  `session_scope()` context manager.
- `init_db()` creates tables from the registered models. We import the model modules here
  so that `Base.metadata` is fully populated before `create_all` runs. (No Alembic yet —
  the schema is young and additive; migrations can be introduced when it stabilizes.)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the project."""


def _make_engine():
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    # future=True style is the default in SQLAlchemy 2.0. pool_pre_ping guards against
    # stale connections if we ever move off SQLite.
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a request-scoped session and guarantee cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts/tests: commit on success, roll back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Importing the model modules registers them on Base.metadata."""
    # Imported for their side effect of registering mappers on Base.metadata.
    from app.agents import models as _agent_models  # noqa: F401
    from app.analytics import models as _an_models  # noqa: F401
    from app.auth import models as _auth_models  # noqa: F401
    from app.chat import models as _chat_models  # noqa: F401
    from app.citations import models as _cite_models  # noqa: F401
    from app.documents import models as _doc_models  # noqa: F401
    from app.evaluation import models as _eval_models  # noqa: F401
    from app.flashcards import models as _fc_models  # noqa: F401
    from app.ingestion import models as _ing_models  # noqa: F401
    from app.knowledge import models as _kg_models  # noqa: F401
    from app.graphreason import models as _greason_models  # noqa: F401
    from app.knowledgeworkspace import models as _kws_models  # noqa: F401
    from app.memory import models as _mem_models  # noqa: F401
    from app.media import models as _media_models  # noqa: F401
    from app.mediaworkspace import models as _mediaws_models  # noqa: F401
    from app.mmcontext import models as _mmc_models  # noqa: F401
    from app.mmretrieval import models as _mmr_models  # noqa: F401
    from app.notes import models as _note_models  # noqa: F401
    from app.observability import models as _obs_models  # noqa: F401
    from app.orchestration import models as _orch_models  # noqa: F401
    from app.reasoning import models as _reason_models  # noqa: F401
    from app.summaries import models as _sum_models  # noqa: F401
    from app.tintel import models as _tintel_models  # noqa: F401
    from app.tretrieval import models as _tret_models  # noqa: F401
    from app.vision import models as _vis_models  # noqa: F401
    from app.workspaces import models as _ws_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
