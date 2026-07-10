"""Unit tests for SummaryService (lifecycle + generation pipeline) with a fake engine."""

from __future__ import annotations

import pytest

from app.summaries.errors import SummaryNotFound, SummaryStateError, SummaryValidationError
from app.summaries.repository import SummaryRepository
from app.summaries.service import SummaryService
from tests.conftest import FakeSummaryEngine

OWNER = "user_1"
WS = "ws_1"


class FakeWorkspaceService:
    def __init__(self):
        self.calls = []

    def adjust_counter(self, workspace_id, owner_id, field, delta):
        self.calls.append((field, delta))


def _service(db):
    ws = FakeWorkspaceService()
    return SummaryService(SummaryRepository(db), ws), ws


def test_create_validates_and_bumps_counter(db_session):
    svc, ws = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="quick")
    assert s.scope == "workspace" and s.status == "queued"
    assert ws.calls == [("summary_count", 1)]
    with pytest.raises(SummaryValidationError):
        svc.create(OWNER, WS, summary_type="essay")
    with pytest.raises(SummaryValidationError):
        svc.create(OWNER, WS, summary_type="quick", scope="document")  # missing document_id


def test_generate_now_persists_sections_and_citations(db_session):
    svc, _ = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="standard")
    out = svc.generate_now(s.id, FakeSummaryEngine())
    assert out.status == "completed"
    assert out.progress == 100
    assert out.section_count == 2
    assert out.token_usage == 42
    assert out.model_name == "llama3"

    _, sections, cits = svc.get_with_sections(s.id, OWNER)
    assert [x.heading for x in sections] == ["Overview", "Conclusions"]
    assert cits[sections[0].id][0].page_number == 3
    assert cits[sections[0].id][0].confidence == 0.88


def test_generate_now_failure_recovers(db_session):
    svc, _ = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="quick")

    class BoomEngine:
        def generate(self, summary, db):
            yield {"type": "plan", "total": 1}
            raise RuntimeError("llm down")

    out = svc.generate_now(s.id, BoomEngine())
    assert out.status == "failed"
    assert "llm down" in out.error


def test_cancel_state_machine(db_session):
    svc, _ = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="quick")
    svc.cancel(s.id, OWNER)
    assert svc.get(s.id, OWNER).status == "cancelled"
    # generate_now respects a pre-cancelled summary (no-op).
    out = svc.generate_now(s.id, FakeSummaryEngine())
    assert out.status == "cancelled"
    # cannot cancel again (not queued/processing)
    with pytest.raises(SummaryStateError):
        svc.cancel(s.id, OWNER)


def test_regenerate_resets_and_reruns(db_session):
    svc, _ = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="standard")
    svc.generate_now(s.id, FakeSummaryEngine())
    reset = svc.reset_for_regenerate(s.id, OWNER)
    assert reset.status == "queued" and reset.version == 2
    assert svc.get_with_sections(s.id, OWNER)[1] == []  # sections cleared
    svc.generate_now(s.id, FakeSummaryEngine())
    assert svc.get(s.id, OWNER).status == "completed"


def test_duplicate_copies_sections(db_session):
    svc, ws = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="standard")
    svc.generate_now(s.id, FakeSummaryEngine())
    ws.calls.clear()
    dup = svc.duplicate(s.id, OWNER)
    assert dup.title.endswith("(copy)")
    assert ws.calls == [("summary_count", 1)]
    _, sections, cits = svc.get_with_sections(dup.id, OWNER)
    assert len(sections) == 2
    assert len(cits[sections[0].id]) == 1


def test_delete_decrements(db_session):
    svc, ws = _service(db_session)
    s = svc.create(OWNER, WS, summary_type="quick")
    ws.calls.clear()
    svc.delete(s.id, OWNER, permanent=True)
    assert ws.calls == [("summary_count", -1)]
    with pytest.raises(SummaryNotFound):
        svc.get(s.id, OWNER)
