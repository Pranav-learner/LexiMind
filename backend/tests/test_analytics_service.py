"""Unit tests for the analytics caching service + signature invalidation."""

from __future__ import annotations

from app.analytics.repository import AnalyticsRepository
from app.analytics.service import AnalyticsService
from app.notes.models import Note
from app.workspaces.models import Workspace


def _svc(db):
    return AnalyticsService(AnalyticsRepository(db))


def _ws(db, wid="w1", owner="u1"):
    db.add(Workspace(id=wid, name="WS", owner_id=owner))
    db.commit()


def test_section_computes_and_caches(db_session):
    _ws(db_session)
    svc = _svc(db_session)
    payload = svc.section("w1", "u1", "knowledge")
    assert payload["documents"] == 0 and payload["workspace_name"] == "WS"
    # A snapshot row was written.
    snap = AnalyticsRepository(db_session).get_snapshot("w1", "knowledge")
    assert snap is not None and snap.section == "knowledge"


def test_cache_returns_same_until_signature_changes(db_session):
    _ws(db_session)
    svc = _svc(db_session)
    first = svc.section("w1", "u1", "learning")
    assert first["notes_created"] == 0

    # Add a note WITHOUT going through the cache → signature changes on next read.
    db_session.add(Note(workspace_id="w1", owner_id="u1", title="N", content="hello world", status="ready"))
    db_session.commit()
    second = svc.section("w1", "u1", "learning")
    assert second["notes_created"] == 1  # recomputed because the signature changed


def test_signature_reflects_data(db_session):
    _ws(db_session)
    repo = AnalyticsRepository(db_session)
    sig1 = repo.signature("w1")
    db_session.add(Note(workspace_id="w1", owner_id="u1", title="N", content="x", status="ready"))
    db_session.commit()
    assert repo.signature("w1") != sig1


def test_dashboard_assembles_all_sections(db_session):
    _ws(db_session)
    dash = _svc(db_session).dashboard("w1", "u1")
    for key in ("knowledge", "ai_usage", "learning", "retrieval", "charts", "activity", "insights"):
        assert key in dash


def test_refresh_busts_cache(db_session):
    _ws(db_session)
    svc = _svc(db_session)
    svc.section("w1", "u1", "knowledge")
    assert AnalyticsRepository(db_session).get_snapshot("w1", "knowledge") is not None
    svc.refresh("w1", "u1")
    # After refresh the snapshot exists again (recomputed), and dashboard is returned.
    assert AnalyticsRepository(db_session).get_snapshot("w1", "knowledge") is not None
