"""Unit tests for pure note validation + text metrics (no DB)."""

from __future__ import annotations

import pytest

from app.notes import validation as v
from app.notes.errors import NoteValidationError


def test_title_defaults_and_normalizes():
    assert v.validate_title(None, default="X") == "X"
    assert v.validate_title("   ", default="X") == "X"
    assert v.validate_title("  a   b ", default="X") == "a b"


def test_title_rejects_too_long_and_control_chars():
    with pytest.raises(NoteValidationError):
        v.validate_title("a" * 301, default="X")
    with pytest.raises(NoteValidationError):
        v.validate_title("bad\x01title", default="X")


def test_note_type_validation():
    assert v.validate_note_type(None) == "study"
    assert v.validate_note_type("REVISION") == "revision"
    with pytest.raises(NoteValidationError):
        v.validate_note_type("essay")


def test_scope_inference_and_rules():
    assert v.validate_scope(None, document_id=None, document_ids=None) == "workspace"
    assert v.validate_scope(None, document_id="d1", document_ids=None) == "document"
    assert v.validate_scope(None, document_id=None, document_ids=["a", "b"]) == "multi"
    with pytest.raises(NoteValidationError):
        v.validate_scope("document", document_id=None, document_ids=None)
    with pytest.raises(NoteValidationError):
        v.validate_scope("multi", document_id=None, document_ids=None)


def test_content_size_guard():
    assert v.validate_content(None) == ""
    with pytest.raises(NoteValidationError):
        v.validate_content("x" * (v.CONTENT_MAX_LEN + 1))


def test_tag_name_and_color():
    assert v.validate_tag_name("  Machine  Learning ") == "Machine Learning"
    with pytest.raises(NoteValidationError):
        v.validate_tag_name("   ")
    assert v.validate_color(None) == "#6366f1"
    assert v.validate_color("#abc") == "#abc"
    with pytest.raises(NoteValidationError):
        v.validate_color("blue")


def test_word_count_and_reading_time():
    assert v.word_count("") == 0
    assert v.word_count("one two three") == 3
    # Fenced code is stripped from the estimate.
    assert v.word_count("hello ```py\nx = 1 + 2\n``` world") == 2
    assert v.reading_minutes(0) == 0
    assert v.reading_minutes(1) == 1          # always at least a minute for non-empty
    assert v.reading_minutes(400) == 2


def test_outline_from_markdown_skips_fenced_code():
    md = "# Title\n\nbody\n\n## Section A\n```\n# not a heading\n```\n### Deep\n"
    outline = v.outline_from_markdown(md)
    assert [(o["level"], o["text"]) for o in outline] == [(1, "Title"), (2, "Section A"), (3, "Deep")]
    assert outline[1]["slug"] == "section-a"


def test_default_note_title():
    assert v.default_note_title(None, source="blank") == "Untitled note"
    assert v.default_note_title("revision", source="document") == "Revision notes"
    assert v.default_note_title("study", source="document", subject="OS") == "Study notes: OS"
