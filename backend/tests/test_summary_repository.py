"""Unit tests for SummaryRepository."""

from __future__ import annotations

from app.summaries.models import Summary, SummaryCitation, SummarySection
from app.summaries.repository import SummaryRepository
from app.summaries.schemas import SortField, SortOrder, StatusFilter

OWNER = "user_1"
WS = "ws_1"


def _sum(repo, *, title="S", stype="standard", status="completed", owner=OWNER, ws=WS, doc=None):
    return repo.create(Summary(
        owner_id=owner, workspace_id=ws, scope="workspace" if not doc else "document",
        document_id=doc, title=title, summary_type=stype, status=status,
    ))


def test_get_owner_scoped_and_soft_delete(db_session):
    repo = SummaryRepository(db_session)
    s = _sum(repo)
    assert repo.get(s.id, OWNER) is not None
    assert repo.get(s.id, "other") is None
    repo.soft_delete(s)
    assert repo.get(s.id, OWNER) is None
    assert repo.get_by_id_only(s.id) is not None  # runner can still find it


def test_list_filters(db_session):
    repo = SummaryRepository(db_session)
    _sum(repo, title="alpha", stype="quick", status="completed")
    _sum(repo, title="beta", stype="detailed", status="processing")
    assert repo.list(OWNER, WS)[1] == 2
    assert repo.list(OWNER, WS, summary_type="quick")[1] == 1
    assert repo.list(OWNER, WS, status=StatusFilter.processing)[1] == 1
    assert repo.list(OWNER, WS, search="alpha")[1] == 1
    items, _ = repo.list(OWNER, WS, sort_by=SortField.title, order=SortOrder.asc)
    assert [i.title for i in items] == ["alpha", "beta"]


def test_sections_and_batched_citations(db_session):
    repo = SummaryRepository(db_session)
    s = _sum(repo)
    sec1 = repo.add_section(SummarySection(summary_id=s.id, heading="A", order=1, content="a"),
                            [SummaryCitation(summary_section_id="", workspace_id=WS, citation_text="c1", page_number=3)])
    repo.add_section(SummarySection(summary_id=s.id, heading="B", order=2, content="b"), [])
    sections = repo.sections(s.id)
    assert [x.heading for x in sections] == ["A", "B"]
    cits = repo.citations_for([x.id for x in sections])
    assert len(cits[sec1.id]) == 1
    assert cits[sec1.id][0].page_number == 3
    assert cits[sec1.id][0].summary_section_id == sec1.id  # linked after flush


def test_clear_sections_and_hard_delete(db_session):
    repo = SummaryRepository(db_session)
    s = _sum(repo)
    repo.add_section(SummarySection(summary_id=s.id, heading="A", order=1, content="a"),
                     [SummaryCitation(summary_section_id="", workspace_id=WS, citation_text="c")])
    repo.clear_sections(s.id)
    assert repo.sections(s.id) == []
    repo.hard_delete(s)
    assert repo.get_by_id_only(s.id) is None
