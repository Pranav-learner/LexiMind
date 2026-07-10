"""Unit tests for ChatService (business rules + message pipeline) with a fake engine."""

from __future__ import annotations

import pytest

from app.chat.errors import ConversationNotFound, ConversationStateError
from app.chat.repository import ConversationRepository, MessageRepository
from app.chat.service import ChatService
from tests.conftest import FakeChatEngine

OWNER = "user_1"
WS = "ws_1"


class FakeWorkspaceService:
    def __init__(self):
        self.calls = []

    def adjust_counter(self, workspace_id, owner_id, field, delta):
        self.calls.append((field, delta))


def _service(db):
    ws = FakeWorkspaceService()
    return ChatService(ConversationRepository(db), MessageRepository(db), ws), ws


def test_create_bumps_chat_count(db_session):
    svc, ws = _service(db_session)
    c = svc.create(OWNER, WS, title="Hi")
    assert c.title == "Hi"
    assert ws.calls == [("chat_count", 1)]


def test_pin_archive_restore_state_machine(db_session):
    svc, _ = _service(db_session)
    c = svc.create(OWNER, WS)
    svc.set_pinned(c.id, OWNER, True)
    assert c.is_pinned is True
    svc.archive(c.id, OWNER)
    with pytest.raises(ConversationStateError):
        svc.archive(c.id, OWNER)
    svc.restore(c.id, OWNER)
    with pytest.raises(ConversationStateError):
        svc.restore(c.id, OWNER)


def test_delete_soft_and_hard_decrements(db_session):
    svc, ws = _service(db_session)
    c = svc.create(OWNER, WS)
    ws.calls.clear()
    svc.delete(c.id, OWNER, permanent=False)
    assert ws.calls == [("chat_count", -1)]
    with pytest.raises(ConversationNotFound):
        svc.get(c.id, OWNER)


def test_run_message_persists_turn_with_citations_and_autotitle(db_session):
    svc, _ = _service(db_session)
    c = svc.create(OWNER, WS)  # default title "New chat"
    events = list(svc.run_message(c.id, OWNER, "What is paging?", FakeChatEngine()))
    types = [e["type"] for e in events]
    assert types[0] == "user"
    assert "token" in types
    assert types[-1] == "done"

    # Conversation now has 2 messages and an auto-generated title.
    fresh = svc.get(c.id, OWNER)
    assert fresh.message_count == 2
    assert fresh.title == "What is paging?"
    assert fresh.last_message_at is not None

    items, cits, total = svc.list_messages(c.id, OWNER)
    assert total == 2
    assistant = [m for m in items if m.role == "assistant"][0]
    assert assistant.content == "Hello world"
    assert assistant.citation_count == 1
    assert len(cits[assistant.id]) == 1
    assert cits[assistant.id][0].page_number == 42


def test_run_message_memory_threads_prior_turns(db_session):
    svc, _ = _service(db_session)
    c = svc.create(OWNER, WS)

    seen = {}

    class RecordingEngine(FakeChatEngine):
        def generate(self, question, workspace_id, history, *, db=None, top_k=None, document_scope=None):
            seen["history_len"] = len(history)
            seen["ws"] = workspace_id
            yield from super().generate(question, workspace_id, history, db=db, top_k=top_k, document_scope=document_scope)

    list(svc.run_message(c.id, OWNER, "first question", RecordingEngine()))
    assert seen["history_len"] == 0  # no prior turns on the first message
    assert seen["ws"] == WS
    list(svc.run_message(c.id, OWNER, "second question", RecordingEngine()))
    assert seen["history_len"] >= 2  # first user + first assistant now in memory


def test_duplicate_copies_history(db_session):
    svc, ws = _service(db_session)
    c = svc.create(OWNER, WS, title="Original")
    list(svc.run_message(c.id, OWNER, "hi", FakeChatEngine()))
    ws.calls.clear()
    dup = svc.duplicate(c.id, OWNER)
    assert dup.title == "Original (copy)"
    assert dup.message_count == 2
    assert ws.calls == [("chat_count", 1)]
    items, _, total = svc.list_messages(dup.id, OWNER)
    assert total == 2


def test_run_message_engine_error_persists_error_turn(db_session):
    svc, _ = _service(db_session)
    c = svc.create(OWNER, WS)

    class BoomEngine:
        def generate(self, *a, **k):
            yield {"type": "token", "text": "partial"}
            raise RuntimeError("llm exploded")

    events = list(svc.run_message(c.id, OWNER, "q", BoomEngine()))
    assert events[-1]["type"] == "error"
    items, _, total = svc.list_messages(c.id, OWNER)
    assert total == 2  # user + error assistant
    assistant = [m for m in items if m.role == "assistant"][0]
    assert assistant.meta["status"] == "error"
