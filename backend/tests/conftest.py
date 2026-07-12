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
from app.optimization import models as _opt_models  # noqa: F401
from app.orchestration import models as _orch_models  # noqa: F401
from app.reasoning import models as _reason_models  # noqa: F401
from app.summaries import models as _sum_models  # noqa: F401
from app.tintel import models as _tintel_models  # noqa: F401
from app.tretrieval import models as _tret_models  # noqa: F401
from app.vision import models as _vis_models  # noqa: F401
from app.workspaces import models as _ws_models  # noqa: F401

from app.retrieval.schemas import derive_document_id


class FakeSummaryEngine:
    """Deterministic stand-in for the faiss-backed summary engine.

    Emits a `plan`, two grounded `section` events (with a citation each), then a `final`, mirroring
    the PipelineSummaryEngine event contract — so the whole generation pipeline (sections,
    citations, progress, persistence) is exercised without retrieval/LLM.
    """

    def __init__(self, sections=None):
        self.sections = sections or [
            {"heading": "Overview", "content": "This is the overview.",
             "citations": [{"chunk_id": "doc_x:0", "document_id": "doc_x", "page_number": 3,
                            "text": "overview evidence", "confidence": 0.88}]},
            {"heading": "Conclusions", "content": "These are the conclusions.",
             "citations": [{"chunk_id": "doc_x:9", "document_id": "doc_x", "page_number": 20,
                            "text": "conclusion evidence", "confidence": 0.77}]},
        ]

    def generate(self, summary, db):
        yield {"type": "plan", "total": len(self.sections), "model": "llama3", "language": "en"}
        for i, sec in enumerate(self.sections, start=1):
            yield {"type": "section", "heading": sec["heading"], "order": i,
                   "content": sec["content"], "citations": sec.get("citations", [])}
        yield {"type": "final", "token_usage": 42}


class FakeNotesEngine:
    """Deterministic stand-in for the faiss-backed notes engine.

    `generate` emits a `plan`, two grounded `section` events (with a citation each), then a
    `final`, mirroring the PipelineNotesEngine contract — so the whole generation pipeline
    (sections, citations, content assembly, progress, persistence) is exercised without
    retrieval/LLM. `assist` echoes a deterministic transformation of the selection.
    """

    def __init__(self, sections=None):
        self.sections = sections or [
            {"heading": "Overview", "content": "- First key point.\n- Second key point.",
             "citations": [{"chunk_id": "doc_x:0", "document_id": "doc_x", "page_number": 3,
                            "text": "overview evidence", "confidence": 0.88}]},
            {"heading": "Key Concepts", "content": "- **Term** — a definition.",
             "citations": [{"chunk_id": "doc_x:9", "document_id": "doc_x", "page_number": 20,
                            "text": "concept evidence", "confidence": 0.77}]},
        ]

    def generate(self, note, db):
        yield {"type": "plan", "total": len(self.sections), "model": "llama3"}
        for i, sec in enumerate(self.sections, start=1):
            yield {"type": "section", "heading": sec["heading"], "order": i,
                   "content": sec["content"], "citations": sec.get("citations", [])}
        yield {"type": "final", "token_usage": 42}

    def assist(self, note, db, *, operation, selection, instruction=None, ground=True):
        return f"[{operation}] {selection}".strip()


class FakeFlashcardEngine:
    """Deterministic stand-in for the faiss-backed flashcard engine.

    Emits a `plan`, then `count` grounded `card` events (each with a citation), then a `final`,
    mirroring the PipelineFlashcardEngine contract — so the whole generation pipeline (bulk card
    insert, citations, progress, deck recount, workspace counter) is exercised without
    retrieval/LLM.
    """

    def __init__(self, per_card_citation=True):
        self.per_card_citation = per_card_citation

    def generate(self, deck, db, *, count):
        yield {"type": "plan", "total": count, "model": "llama3"}
        for i in range(count):
            cits = [{"chunk_id": f"doc_x:{i}", "document_id": "doc_x", "page_number": i + 1,
                     "text": f"evidence {i}", "confidence": 0.8}] if self.per_card_citation else []
            yield {"type": "card", "front": f"Question {i}?", "back": f"Answer {i}.",
                   "hint": f"Hint {i}", "card_type": "basic", "citations": cits}
        yield {"type": "final", "token_usage": 21}


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
    from app.analytics.api import router as analytics_router
    from app.citations.api import router as citations_router
    from app.flashcards.api import get_flashcards_runner
    from app.flashcards.api import router as flashcards_router
    from app.flashcards.runner import InlineRunner as FlashcardInlineRunner
    from app.ingestion.api import get_ingestion_runner
    from app.ingestion.api import router as ingestion_router
    from app.ingestion.engines import FakeMultimodalEngine
    from app.ingestion.runner import InlineRunner as IngestionInlineRunner
    from app.media.api import get_media_runner
    from app.media.api import router as media_router
    from app.media.engines import FakeMediaEngine
    from app.media.runner import InlineRunner as MediaInlineRunner
    from app.mediaworkspace.api import (
        get_flashcards_runner as get_mediaws_flashcards_runner,
        get_notes_runner as get_mediaws_notes_runner,
        get_summary_runner as get_mediaws_summary_runner,
        get_temporal_chat_engine,
    )
    from app.mediaworkspace.api import router as mediaworkspace_router
    from app.mediaworkspace.engine import TemporalChatEngine
    from app.agents.api import get_agent_services
    from app.agents.api import router as agents_router
    from app.agents.task_api import router as agent_tasks_router
    from app.reasoning.api import router as verification_router
    from app.orchestration.api import router as orchestration_router
    from app.knowledge.api import get_graph_runner
    from app.knowledge.api import router as knowledge_router
    from app.memory.api import router as memory_router
    from app.graphreason.api import router as graphreason_router
    from app.knowledgeworkspace.api import get_graph_chat_engine
    from app.knowledgeworkspace.api import router as knowledgeworkspace_router
    from app.evaluation.api import router as evaluation_router
    from app.observability.api import router as observability_router
    from app.optimization.api import router as optimization_router
    from app.knowledgeworkspace.engine import GraphChatEngine
    from app.knowledge.runner import InlineRunner as GraphInlineRunner
    from app.vision.api import get_vision_runner
    from app.vision.api import router as vision_router
    from app.vision.engines import FakeVisionEngine
    from app.vision.runner import InlineRunner as VisionInlineRunner
    from app.mmretrieval.api import get_text_retriever
    from app.mmretrieval.api import router as mmsearch_router
    from app.mmretrieval.retrievers import LexicalTextRetriever
    from app.mmcontext.api import router as mmcontext_router
    from app.mmworkspace.api import router as mmworkspace_router
    from app.notes.api import get_notes_engine, get_notes_runner
    from app.notes.api import router as notes_router
    from app.notes.api import tag_router as notes_tag_router
    from app.notes.runner import InlineRunner as NoteInlineRunner
    from app.summaries.api import get_summary_runner
    from app.summaries.api import router as summary_router
    from app.summaries.runner import InlineRunner
    from app.tintel.api import router as tintel_router
    from app.tretrieval.api import router as tretrieval_router
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
    application.include_router(summary_router)
    application.include_router(notes_router)
    application.include_router(notes_tag_router)
    application.include_router(flashcards_router)
    application.include_router(citations_router)
    application.include_router(analytics_router)
    application.include_router(ingestion_router)
    application.include_router(media_router)
    application.include_router(mediaworkspace_router)
    application.include_router(agents_router)
    application.include_router(agent_tasks_router)
    application.include_router(verification_router)
    application.include_router(orchestration_router)
    application.include_router(knowledge_router)
    application.include_router(memory_router)
    application.include_router(graphreason_router)
    application.include_router(knowledgeworkspace_router)
    application.include_router(evaluation_router)
    application.include_router(observability_router)
    application.include_router(optimization_router)
    application.include_router(tintel_router)
    application.include_router(tretrieval_router)
    application.include_router(vision_router)
    application.include_router(mmsearch_router)
    application.include_router(mmcontext_router)
    application.include_router(mmworkspace_router)
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_index_context] = lambda: fake_index
    application.dependency_overrides[get_ingestor] = lambda: make_fake_ingest()
    application.dependency_overrides[get_chat_engine] = lambda: FakeChatEngine()
    # Summaries run inline (synchronously) in tests, using the same in-memory DB + a fake engine.
    application.dependency_overrides[get_summary_runner] = lambda: InlineRunner(SessionFactory, FakeSummaryEngine())
    # Notes: inline runner (async AI generation) + fake engine (also serves assist) in tests.
    application.dependency_overrides[get_notes_runner] = lambda: NoteInlineRunner(SessionFactory, FakeNotesEngine())
    application.dependency_overrides[get_notes_engine] = lambda: FakeNotesEngine()
    # Flashcard decks generate inline (synchronously) in tests with a fake engine.
    application.dependency_overrides[get_flashcards_runner] = lambda: FlashcardInlineRunner(SessionFactory, FakeFlashcardEngine())
    # Multimodal ingestion runs inline (synchronously) in tests with a deterministic fake engine.
    application.dependency_overrides[get_ingestion_runner] = lambda: IngestionInlineRunner(SessionFactory, FakeMultimodalEngine())
    # Audio/Video media processing runs inline (synchronously) in tests with a deterministic fake engine.
    application.dependency_overrides[get_media_runner] = lambda: MediaInlineRunner(SessionFactory, FakeMediaEngine())
    # Media AI chat: real temporal retrieval over the in-memory DB, but a FAKED LLM (no ollama) — the
    # answer echoes the citation count so tests can assert the prompt was grounded + answered.
    def _fake_media_answer(prompt: str) -> str:
        n = prompt.count("[")
        return f"Grounded temporal answer citing {n} moment(s). [1]"
    application.dependency_overrides[get_temporal_chat_engine] = lambda: TemporalChatEngine(answer_fn=_fake_media_answer)
    # Knowledge-asset actions generate inline (synchronously) with the same fake engines used elsewhere.
    application.dependency_overrides[get_mediaws_summary_runner] = lambda: InlineRunner(SessionFactory, FakeSummaryEngine())
    application.dependency_overrides[get_mediaws_notes_runner] = lambda: NoteInlineRunner(SessionFactory, FakeNotesEngine())
    application.dependency_overrides[get_mediaws_flashcards_runner] = lambda: FlashcardInlineRunner(SessionFactory, FakeFlashcardEngine())
    # Agent runtime: FAKED single answer function (no ollama) + inline generation runners (synchronous).
    def _fake_agent_answer(prompt: str) -> str:
        return f"Agent answer synthesized from {prompt.count('### Evidence')} evidence block(s)."
    application.dependency_overrides[get_agent_services] = lambda: {
        "answer_fn": _fake_agent_answer,
        "summary_runner": InlineRunner(SessionFactory, FakeSummaryEngine()),
        "notes_runner": NoteInlineRunner(SessionFactory, FakeNotesEngine()),
        "flashcard_runner": FlashcardInlineRunner(SessionFactory, FakeFlashcardEngine()),
    }
    # Vision analysis runs inline (synchronously) in tests with a deterministic fake engine.
    application.dependency_overrides[get_vision_runner] = lambda: VisionInlineRunner(SessionFactory, FakeVisionEngine())
    # Multimodal search uses the faiss-free lexical text retriever in tests (no FAISS/torch).
    application.dependency_overrides[get_text_retriever] = lambda: LexicalTextRetriever()
    # Knowledge-graph construction runs inline (synchronously) in tests with the deterministic extractor.
    application.dependency_overrides[get_graph_runner] = lambda: GraphInlineRunner(SessionFactory)
    # AI Graph Chat: real graph retrieval+reasoning over the in-memory DB, FAKED LLM (no ollama).
    def _fake_graph_answer(prompt: str) -> str:
        return f"Graph-grounded answer citing {prompt.count('[')} knowledge item(s). [1]"
    application.dependency_overrides[get_graph_chat_engine] = lambda: GraphChatEngine(answer_fn=_fake_graph_answer)
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
