"""Fixtures for the Phase-3 workspace/auth/document tests.

These tests use an in-memory SQLite database (StaticPool => one shared connection so every
session sees the same data) and a MINIMAL FastAPI app that mounts only the auth + workspace +
document routers. Building a minimal app on purpose avoids importing `app.core.state` (and
therefore FAISS / sentence-transformers / torch), so this suite runs with just SQLAlchemy +
FastAPI. The document routes' heavy dependencies (vector store, ingestion) are overridden with
fast in-memory fakes so the full document lifecycle can be exercised over HTTP.
"""

from __future__ import annotations

import os
import tempfile

# Point uploads at a throwaway temp dir BEFORE app.core.config's settings singleton is built,
# so tests never write into the real backend/uploaded_pdfs. Reranker off keeps imports light.
os.environ.setdefault("LEXIMIND_ENABLE_RERANKER", "0")
os.environ.setdefault("LEXIMIND_UPLOAD_DIR", tempfile.mkdtemp(prefix="leximind_test_uploads_"))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db

# Import models so their tables are registered on Base.metadata before create_all.
from app.auth import models as _auth_models  # noqa: F401
from app.chat import models as _chat_models  # noqa: F401
from app.documents import models as _doc_models  # noqa: F401
from app.workspaces import models as _ws_models  # noqa: F401

from app.retrieval.schemas import derive_document_id


class FakeChatEngine:
    """Deterministic stand-in for the real (faiss-backed) chat engine.

    Emits a couple of token events then a `final` with fake citations + metrics, mirroring the
    PipelineChatEngine event contract — so the full chat pipeline (persistence, streaming,
    citations, memory) is exercised without retrieval/LLM.
    """

    def __init__(self, tokens=("Hello", " world"), citations=None):
        self.tokens = tokens
        self.citations = citations if citations is not None else [
            {"chunk_id": "doc_x:0", "document_id": "doc_x", "source": "OS.pdf",
             "page_number": 42, "section": "Memory", "text": "virtual memory", "confidence": 0.91},
        ]

    def generate(self, question, workspace_id, history, *, db=None, top_k=None, document_scope=None):
        # Echo history length so tests can assert memory is threaded through.
        for t in self.tokens:
            yield {"type": "token", "text": t}
        yield {
            "type": "final",
            "answer": "".join(self.tokens),
            "citations": self.citations,
            "retrieval_ms": 5, "context_size": 123, "token_usage": 7, "latency_ms": 9,
        }


# --------------------------------------------------------------------- in-memory index fakes
class FakeBM25:
    """Stand-in for BM25Retriever: only the corpus-sync hooks the documents layer calls."""

    def __init__(self):
        self.dirty = False
        self.added = 0

    def mark_dirty(self):
        self.dirty = True

    def add_documents(self, count: int = 1):
        self.added += count
        self.dirty = True


class _FakeIndex:
    def __init__(self, store):
        self._store = store

    @property
    def ntotal(self):
        return len(self._store.metadata)


class FakeVectorStore:
    """In-memory VectorStore with the exact surface the documents layer uses."""

    def __init__(self):
        self.metadata = []
        self.dimension = 384
        self.index = _FakeIndex(self)
        self.saved = 0

    def add(self, embedding, metadata):
        self.metadata.append(metadata)

    def size(self):
        return len(self.metadata)

    def count_where(self, predicate):
        return sum(1 for m in self.metadata if predicate(m))

    def remove_where(self, predicate):
        keep = [m for m in self.metadata if not predicate(m)]
        removed = len(self.metadata) - len(keep)
        self.metadata = keep
        return removed

    def save(self):
        self.saved += 1


def make_fake_ingest(chunks_per_doc: int = 3):
    """A fast, deterministic ingest that mimics ingest_pdf's contract on a FakeVectorStore."""

    def ingest(path, filename, vector_store, bm25_retriever=None, *, workspace_id=None,
               on_stage=None, replace_existing=False):
        document_id = derive_document_id(filename)
        if replace_existing:
            removed = vector_store.remove_where(
                lambda m: m.get("document_id") == document_id and m.get("workspace_id") == workspace_id
            )
            if removed and bm25_retriever is not None:
                bm25_retriever.mark_dirty()
        for stage in ("text_extraction", "chunking", "embedding", "faiss_indexing",
                      "bm25_indexing", "metadata"):
            if on_stage:
                on_stage(stage)
        for i in range(chunks_per_doc):
            vector_store.add(
                [0.0] * vector_store.dimension,
                {
                    "document_id": document_id,
                    "workspace_id": workspace_id,
                    "text": f"chunk {i} of {filename}",
                    "page_number": 1,
                    "chunk_index": i,
                },
            )
        vector_store.save()
        if bm25_retriever is not None:
            bm25_retriever.add_documents(chunks_per_doc)
        return {
            "filename": filename,
            "document_id": document_id,
            "workspace_id": workspace_id,
            "pages_extracted": 2,
            "total_chunks": chunks_per_doc,
            "word_count": chunks_per_doc * 4,
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dimension": 384,
            "sample_text": "hello world this is english sample text",
        }

    return ingest


# --------------------------------------------------------------------- DB fixtures
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
def fake_index():
    """The (vector_store, bm25) pair injected into the document routes; shared per test."""
    return FakeVectorStore(), FakeBM25()


@pytest.fixture()
def app(engine, SessionFactory, fake_index):
    from fastapi import FastAPI

    from app.auth.api import router as auth_router
    from app.chat.api import get_chat_engine
    from app.chat.api import router as chat_router
    from app.documents.api import get_index_context, get_ingestor
    from app.documents.api import router as document_router
    from app.documents.reading_api import router as reading_router
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
    application.include_router(document_router)
    application.include_router(reading_router)
    application.include_router(chat_router)
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_index_context] = lambda: fake_index
    application.dependency_overrides[get_ingestor] = lambda: make_fake_ingest()
    application.dependency_overrides[get_chat_engine] = lambda: FakeChatEngine()
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


@pytest.fixture()
def workspace(auth):
    """Create a workspace for the authed user; return (client, headers, user_id, workspace_id)."""
    client, headers, user_id = auth
    resp = client.post("/workspaces", json={"name": "Library WS"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return client, headers, user_id, resp.json()["id"]
