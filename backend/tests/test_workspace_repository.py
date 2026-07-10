"""Unit tests for WorkspaceRepository (owner-scoping, listing, soft-delete, counters)."""

from app.workspaces.models import Workspace
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.schemas import ArchivedFilter, SortField, SortOrder

OWNER = "user_owner"
OTHER = "user_other"


def _mk(repo, owner, name, **kw):
    return repo.create(Workspace(name=name, owner_id=owner, **kw))


def test_create_and_get_scoped_to_owner(db_session):
    repo = WorkspaceRepository(db_session)
    ws = _mk(repo, OWNER, "Alpha")
    assert repo.get(ws.id, OWNER).id == ws.id
    # Another owner cannot fetch it.
    assert repo.get(ws.id, OTHER) is None


def test_name_exists_case_insensitive_and_scoped(db_session):
    repo = WorkspaceRepository(db_session)
    ws = _mk(repo, OWNER, "Machine Learning")
    assert repo.name_exists(OWNER, "machine learning")
    # Excluding the row itself frees the name (used by rename to keep the same name).
    assert not repo.name_exists(OWNER, "machine learning", exclude_id=ws.id)
    assert not repo.name_exists(OTHER, "machine learning")  # different owner


def test_soft_delete_hides_from_queries(db_session):
    repo = WorkspaceRepository(db_session)
    ws = _mk(repo, OWNER, "Temp")
    repo.soft_delete(ws)
    assert repo.get(ws.id, OWNER) is None
    assert repo.get(ws.id, OWNER, include_deleted=True) is not None
    # A soft-deleted name is free again.
    assert not repo.name_exists(OWNER, "temp")


def test_list_pagination_and_total(db_session):
    repo = WorkspaceRepository(db_session)
    for i in range(25):
        _mk(repo, OWNER, f"WS {i:02d}")
    items, total = repo.list(OWNER, page=1, page_size=10)
    assert total == 25
    assert len(items) == 10
    items_p3, _ = repo.list(OWNER, page=3, page_size=10)
    assert len(items_p3) == 5


def test_list_search_matches_name_and_description(db_session):
    repo = WorkspaceRepository(db_session)
    _mk(repo, OWNER, "Operating Systems", description="kernels and scheduling")
    _mk(repo, OWNER, "Cooking", description="pasta recipes")
    items, total = repo.list(OWNER, search="schedul")
    assert total == 1 and items[0].name == "Operating Systems"


def test_list_archived_filter(db_session):
    repo = WorkspaceRepository(db_session)
    a = _mk(repo, OWNER, "Active")
    b = _mk(repo, OWNER, "Archived")
    b.is_archived = True
    repo.save(b)
    active, n_active = repo.list(OWNER, archived=ArchivedFilter.active)
    archived, n_arch = repo.list(OWNER, archived=ArchivedFilter.archived)
    both, n_both = repo.list(OWNER, archived=ArchivedFilter.all)
    assert [w.name for w in active] == ["Active"]
    assert [w.name for w in archived] == ["Archived"]
    assert n_both == 2


def test_list_sorting(db_session):
    repo = WorkspaceRepository(db_session)
    _mk(repo, OWNER, "Banana")
    _mk(repo, OWNER, "Apple")
    _mk(repo, OWNER, "Cherry")
    items, _ = repo.list(OWNER, sort_by=SortField.name, order=SortOrder.asc)
    assert [w.name for w in items] == ["Apple", "Banana", "Cherry"]


def test_adjust_counter_never_negative(db_session):
    repo = WorkspaceRepository(db_session)
    ws = _mk(repo, OWNER, "Counted")
    repo.adjust_counter(ws, "document_count", 3)
    assert ws.document_count == 3
    repo.adjust_counter(ws, "document_count", -10)
    assert ws.document_count == 0
