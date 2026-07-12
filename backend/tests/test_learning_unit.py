"""Unit tests for the Phase-8 Module-4 Continuous Learning platform — pure/offline (no HTTP).

Covers feedback sentiment derivation, the error analyzer's categorization + clustering, the prompt/retrieval/
agent learning engines, and the dataset builder — all against an in-memory DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.learning.models  # noqa: F401
import app.workspaces.models  # noqa: F401
import app.reasoning.models  # noqa: F401
import app.evaluation.models  # noqa: F401
from app.learning.analyzer import ErrorAnalyzer
from app.learning.feedback import FeedbackManager, _derive_sentiment
from app.learning.interfaces import FailureCluster, FailureSignal
from app.learning.learners import AgentLearningEngine, PromptLearningEngine, RetrievalLearningEngine


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    from app.workspaces.models import Workspace
    session.add(Workspace(id="ws", owner_id="o", name="WS"))
    session.commit()
    yield session
    session.close()


# --------------------------------------------------------------------- feedback
def test_derive_sentiment():
    assert _derive_sentiment("thumbs_down", None, "") == "negative"
    assert _derive_sentiment("thumbs_up", None, "") == "positive"
    assert _derive_sentiment("star", 1, "") == "negative" and _derive_sentiment("star", 5, "") == "positive"
    assert _derive_sentiment("star", 3, "") == "neutral"
    assert _derive_sentiment("correction", None, "") == "negative"


def test_feedback_manager_summary(db):
    fm = FeedbackManager(db)
    fm.submit("ws", "o", target_type="answer", target_id="a", kind="thumbs_down", comment="wrong")
    fm.submit("ws", None, target_type="answer", target_id="b", kind="thumbs_up")  # anonymous
    fm.submit("ws", "o", target_type="answer", target_id="c", kind="star", rating=5)
    s = fm.summary("ws", "o")
    assert s["total"] == 3 and s["by_sentiment"]["negative"] == 1 and s["avg_rating"] == 5.0
    anon = [f for f in fm.list("ws", "o") if f.owner_id is None]
    assert len(anon) == 1                                # anonymous feedback stored


# --------------------------------------------------------------------- analyzer
def test_analyzer_categorizes_and_clusters(db):
    fm = FeedbackManager(db)
    fm.submit("ws", "o", target_type="citation", target_id="c1", kind="thumbs_down", comment="broken link")
    fm.submit("ws", "o", target_type="retrieval", target_id="r1", kind="thumbs_down", comment="missing docs")
    from app.reasoning.models import VerificationLog
    db.add(VerificationLog(id="v1", workspace_id="ws", owner_id="o", status="unsupported",
                           overall_confidence=0.2, unsupported=3, contradictions_found=1, task_type="research"))
    db.commit()
    an = ErrorAnalyzer(db)
    analysis = an.analyze("ws", "o")
    cats = analysis["by_category"]
    assert cats.get("bad_citation") == 1 and cats.get("missing_retrieval") == 1 and cats.get("hallucination") == 1
    assert len(analysis["clusters"]) >= 1
    # critical (hallucination w/ contradictions) sorts first
    assert analysis["clusters"][0].severity == "critical"


# --------------------------------------------------------------------- learners
def _sig(cat, **sig):
    return FailureSignal(source="x", category=cat, detail=cat, keywords=[cat], signals=sig)


def test_prompt_learner_recommends_on_hallucination():
    recs = PromptLearningEngine().analyze([_sig("hallucination"), _sig("hallucination")], [])
    assert recs and recs[0].category == "prompt" and "PromptPackage" in recs[0].affected_components
    assert recs[0].confidence > 0


def test_retrieval_learner_recommends_on_recall_gap():
    recs = RetrievalLearningEngine().analyze([_sig("missing_retrieval"), _sig("low_confidence"), _sig("low_confidence")], [])
    kinds = {r.title for r in recs}
    assert any("retrieval K" in t or "graph" in t for t in kinds)
    assert all("Retrieval Engine" in r.affected_components for r in recs)


def test_agent_learner_recommends_on_failures():
    sigs = [_sig("agent_failure", retries=2), _sig("agent_failure", retries=1), _sig("agent_failure", retries=3)]
    recs = AgentLearningEngine().analyze(sigs, [])
    assert recs and recs[0].category == "agent" and recs[0].severity == "critical"
    assert recs[0].evidence["cumulative_retries"] == 6


def test_learner_returns_nothing_without_signals():
    assert PromptLearningEngine().analyze([], []) == []
    assert RetrievalLearningEngine().analyze([], []) == []
    assert AgentLearningEngine().analyze([], []) == []


# --------------------------------------------------------------------- dataset builder
def test_dataset_builder_from_corrections(db):
    fm = FeedbackManager(db)
    fm.submit("ws", "o", target_type="answer", target_id="a", kind="correction",
              comment="what is X?", correction="X is Y.")
    from app.learning.dataset_builder import DatasetBuilder
    from app.learning.analyzer import ErrorAnalyzer
    signals = ErrorAnalyzer(db).collect("ws", "o")
    out = DatasetBuilder(db).build_from_failures("ws", "o", signals=signals)
    assert out["created"] and out["item_count"] >= 1
    from app.evaluation.models import EvalItem
    items = db.query(EvalItem).filter(EvalItem.dataset_id == out["dataset_id"]).all()
    assert any(i.expected_answer == "X is Y." for i in items)   # correction became a golden answer
