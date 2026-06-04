"""Unit tests for EvidenceRanker."""

from app.context.ranking import EvidenceRanker
from app.context.schemas import Evidence
from tests.test_context_helpers import mk


def _ev(chunk_id, text, *, score, **kw):
    return Evidence.from_chunk(mk(chunk_id, text, score=score, **kw))


def test_higher_retrieval_score_ranks_higher_all_else_equal():
    a = _ev("a", "process scheduling details", score=0.9, section="Scheduling")
    b = _ev("b", "process scheduling details", score=0.1, section="Scheduling")
    ranked = EvidenceRanker().rank([b, a], query_keywords=["scheduling"])
    assert ranked[0].chunk_id == "a"
    assert ranked[0].evidence_score > ranked[1].evidence_score


def test_metadata_relevance_boosts_section_match():
    # Equal retrieval score; one has the query keyword in its section/topic.
    a = _ev("a", "generic body text", score=0.5, section="Process Scheduling")
    b = _ev("b", "generic body text", score=0.5, section="Unrelated Topic")
    ranked = EvidenceRanker().rank([b, a], query_keywords=["scheduling", "process"])
    assert ranked[0].chunk_id == "a"


def test_citation_confidence_breaks_ties():
    # Equal score & no keywords; complete citation (has page+source+doc) should win over incomplete.
    a = _ev("a", "text", score=0.5, page_number=3)                   # complete
    b = _ev("b", "text", score=0.5, page_number=None)                # incomplete (no page)
    ranked = EvidenceRanker().rank([b, a], query_keywords=[])
    assert ranked[0].chunk_id == "a"


def test_empty_input():
    assert EvidenceRanker().rank([], ["x"]) == []
