"""Fixtures for the Phase-3 workspace/auth tests.

These tests use an in-memory SQLite database (StaticPool => one shared connection so every
session sees the same data) and a MINIMAL FastAPI app that mounts only the auth + workspace
routers. Building a minimal app on purpose avoids importing `app.core.state` (and therefore
FAISS / sentence-transformers / torch), so this suite runs with just SQLAlchemy + FastAPI.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db

# Import models so their tables are registered on Base.metadata before create_all.
from app.auth import models as _auth_models  # noqa: F401
from app.workspaces import models as _ws_models  # noqa: F401


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def SessionFactory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def db_session(SessionFactory):
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def app(engine, SessionFactory):
    from fastapi import FastAPI

    from app.auth.api import router as auth_router
    from app.workspaces.api import router as workspace_router

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    application = FastAPI()
    application.include_router(auth_router)
    application.include_router(workspace_router)
    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def auth(client):
    """Register a user and return (client, headers, user_id)."""
    resp = client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "supersecret1", "display_name": "Alice"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return client, headers, body["user"]["id"]
