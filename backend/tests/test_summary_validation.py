"""Unit tests for summary validation + engine section planning (pure, no faiss)."""

from __future__ import annotations

import pytest

from app.summaries import validation
from app.summaries.engine import PipelineSummaryEngine
from app.summaries.errors import SummaryValidationError


def test_summary_type_validation():
    assert validation.validate_summary_type(None) == "standard"
    assert validation.validate_summary_type("BULLET") == "bullet"
    with pytest.raises(SummaryValidationError):
        validation.validate_summary_type("essay")


def test_scope_inference_and_requirements():
    assert validation.validate_scope(None, document_id="d1", document_ids=None) == "document"
    assert validation.validate_scope(None, document_id=None, document_ids=["a", "b"]) == "multi"
    assert validation.validate_scope(None, document_id=None, document_ids=None) == "workspace"
    with pytest.raises(SummaryValidationError):
        validation.validate_scope("document", document_id=None, document_ids=None)
    with pytest.raises(SummaryValidationError):
        validation.validate_scope("multi", document_id=None, document_ids=None)


def test_title_default_and_validation():
    assert validation.validate_title(None, default="Quick summary") == "Quick summary"
    assert validation.validate_title("  My  Title ", default="x") == "My Title"
    with pytest.raises(SummaryValidationError):
        validation.validate_title("a" * 301, default="x")


def test_default_title_labels():
    assert validation.default_title("bullet", scope="document") == "Bullet summary"
    assert "workspace" in validation.default_title("standard", scope="workspace")
    assert validation.default_title("detailed", scope="document", subject="OS.pdf") == "Detailed summary: OS.pdf"


class _Sum:
    def __init__(self, summary_type, scope="workspace"):
        self.summary_type = summary_type
        self.scope = scope


def test_engine_section_plans_are_type_aware():
    eng = PipelineSummaryEngine()
    assert len(eng._plan_sections(_Sum("quick"), [], None, None)) == 1
    assert len(eng._plan_sections(_Sum("bullet"), [], None, None)) == 1
    assert len(eng._plan_sections(_Sum("standard"), [], None, None)) == 3
    # detailed without a single document → generic theme plan
    assert len(eng._plan_sections(_Sum("detailed", scope="workspace"), [], None, None)) == 5


def test_engine_synthesis_only_for_deep_types():
    eng = PipelineSummaryEngine()
    assert eng._needs_synthesis(_Sum("detailed")) is True
    assert eng._needs_synthesis(_Sum("chapterwise")) is True
    assert eng._needs_synthesis(_Sum("quick")) is False
