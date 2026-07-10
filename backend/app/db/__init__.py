"""Relational persistence layer (SQLite via SQLAlchemy).

WHY this package exists (Phase 3, Module 1):
- Before Phase 3, LexiMind had no database. All persistence was the FAISS index plus a
  parallel `vector_metadata.json` list — perfect for vectors, wrong for structured domain
  rows (users, workspaces) that need uniqueness constraints, indexes, and relations.
- This package introduces the project's FIRST relational store. It is intentionally thin:
  a single engine + session factory + declarative Base, kept separate from the retrieval
  singletons in `app/core/state.py` so the vector layer and the domain layer stay decoupled.

Offline-first: the default database is a single local SQLite file (see Settings.database_url),
so there is no external service to run.
"""

from app.db.base import Base, SessionLocal, engine, get_db, init_db, session_scope

__all__ = ["Base", "SessionLocal", "engine", "get_db", "init_db", "session_scope"]
