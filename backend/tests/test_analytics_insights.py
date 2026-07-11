"""Unit tests for the recommendation engine (data-driven, deterministic)."""

from __future__ import annotations

from datetime import datetime

from app.analytics.aggregators import AggContext
from app.analytics.insights import generate_insights


def _ctx(db_session):
    return AggContext(db=db_session, workspace_id="w1", owner_id="u1", now=datetime(2026, 7, 11, 12, 0))


def _sections():
    knowledge = {"documents": 6, "pages": 100, "chunks": 50}
    ai_usage = {"flashcards_generated": 20}
    learning = {"study_streak_days": 5, "cards_reviewed": 30, "due_today": 3, "new_cards": 2,
                "mastered_cards": 15, "retention": 0.5}
    documents = {"items": [
        {"id": "d1", "display_name": "Operating Systems", "summaries": 0, "citation_count": 9, "question_frequency": 2},
        {"id": "d2", "display_name": "Networking", "summaries": 2, "citation_count": 1, "question_frequency": 7},
    ]}
    return knowledge, ai_usage, learning, documents


def test_rules_fire_and_rank(db_session):
    insights = generate_insights(_ctx(db_session), *_sections())
    ids = {i["id"] for i in insights}
    assert "streak" in ids                    # 5-day streak → positive
    assert "due" in ids                        # cards due
    assert "mastery" in ids                    # 75% mastered
    assert "retention" in ids                  # 50% < 60% → warning
    assert "coverage_summary" in ids           # d1 has no summary
    assert "top_source" in ids                 # d1 most cited
    assert "top_asked" in ids                  # d2 highest question frequency
    assert "milestone_docs" in ids             # 6 documents

    # Warnings rank ahead of info/positive.
    severities = [i["severity"] for i in insights]
    assert severities == sorted(severities, key=lambda s: {"warning": 0, "info": 1, "positive": 2}[s])


def test_mastery_percentage(db_session):
    insights = generate_insights(_ctx(db_session), *_sections())
    mastery = next(i for i in insights if i["id"] == "mastery")
    assert "75%" in mastery["title"]


def test_no_flashcards_no_mastery_or_due(db_session):
    knowledge = {"documents": 1, "pages": 3, "chunks": 2}
    ai_usage = {"flashcards_generated": 0}
    learning = {"study_streak_days": 0, "cards_reviewed": 0, "due_today": 0, "new_cards": 0,
                "mastered_cards": 0, "retention": 1.0}
    documents = {"items": []}
    ids = {i["id"] for i in generate_insights(_ctx(db_session), knowledge, ai_usage, learning, documents)}
    assert "mastery" not in ids and "due" not in ids and "streak" not in ids


def test_actions_have_routes(db_session):
    insights = generate_insights(_ctx(db_session), *_sections())
    due = next(i for i in insights if i["id"] == "due")
    assert due["action_route"] and "/flashcards/review" in due["action_route"]
