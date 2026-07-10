"""Unit tests for WorkspaceService business rules."""

import pytest

from app.workspaces.errors import (
    DuplicateWorkspaceName,
    WorkspaceNotFound,
    WorkspaceStateError,
    WorkspaceValidationError,
)
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

OWNER = "user_1"


def _service(db):
    return WorkspaceService(WorkspaceRepository(db))


def test_create_normalizes_and_defaults(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="  Research   Papers ")
    assert ws.name == "Research Papers"
    assert ws.icon == "📁" and ws.color == "#6366f1"
    assert ws.document_count == 0 and not ws.is_archived


def test_create_duplicate_name_rejected(db_session):
    svc = _service(db_session)
    svc.create(OWNER, name="SIH 2026")
    with pytest.raises(DuplicateWorkspaceName):
        svc.create(OWNER, name="sih 2026")  # case-insensitive collision


def test_create_invalid_name_rejected(db_session):
    svc = _service(db_session)
    with pytest.raises(WorkspaceValidationError):
        svc.create(OWNER, name="   ")


def test_update_fields(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Old")
    updated = svc.update(ws.id, OWNER, name="New", description="desc", icon="🧠", color="#112233")
    assert updated.name == "New"
    assert updated.description == "desc"
    assert updated.icon == "🧠"
    assert updated.color == "#112233"


def test_update_keeping_same_name_is_allowed(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Stable")
    # Renaming to the same name must not trip the duplicate check.
    updated = svc.update(ws.id, OWNER, name="Stable", description="changed")
    assert updated.description == "changed"


def test_update_to_existing_name_rejected(db_session):
    svc = _service(db_session)
    svc.create(OWNER, name="A")
    b = svc.create(OWNER, name="B")
    with pytest.raises(DuplicateWorkspaceName):
        svc.update(b.id, OWNER, name="A")


def test_archive_and_restore(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Archive Me")
    svc.archive(ws.id, OWNER)
    assert svc.get(ws.id, OWNER).is_archived
    with pytest.raises(WorkspaceStateError):
        svc.archive(ws.id, OWNER)  # already archived
    svc.restore(ws.id, OWNER)
    assert not svc.get(ws.id, OWNER).is_archived
    with pytest.raises(WorkspaceStateError):
        svc.restore(ws.id, OWNER)  # not archived


def test_soft_delete_then_not_found(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Doomed")
    svc.delete(ws.id, OWNER)  # soft by default
    with pytest.raises(WorkspaceNotFound):
        svc.get(ws.id, OWNER)


def test_hard_delete_frees_name(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Unique")
    svc.delete(ws.id, OWNER, permanent=True)
    # Name is reusable after a permanent delete.
    again = svc.create(OWNER, name="Unique")
    assert again.id != ws.id


def test_operations_scoped_to_owner(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Private")
    with pytest.raises(WorkspaceNotFound):
        svc.get(ws.id, "someone_else")


def test_counter_maintenance(db_session):
    svc = _service(db_session)
    ws = svc.create(OWNER, name="Docs")
    svc.adjust_counter(ws.id, OWNER, "document_count", 2)
    assert svc.get(ws.id, OWNER).document_count == 2
