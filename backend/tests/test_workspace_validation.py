"""Unit tests for workspace field validation (pure functions, no DB)."""

import pytest

from app.workspaces import validation
from app.workspaces.errors import WorkspaceValidationError


def test_valid_name_is_trimmed_and_collapsed():
    assert validation.validate_name("  Operating   Systems  ") == "Operating Systems"


def test_empty_name_rejected():
    with pytest.raises(WorkspaceValidationError):
        validation.validate_name("   ")


def test_name_too_long_rejected():
    with pytest.raises(WorkspaceValidationError):
        validation.validate_name("x" * 121)


def test_name_with_forbidden_chars_rejected():
    for bad in ["a/b", "a\\b", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", "a:b"]:
        with pytest.raises(WorkspaceValidationError):
            validation.validate_name(bad)


def test_name_with_control_char_rejected():
    with pytest.raises(WorkspaceValidationError):
        validation.validate_name("bad\x01name")


def test_unicode_name_allowed():
    assert validation.validate_name("Systèmes d'exploitation") == "Systèmes d'exploitation"


def test_description_length_capped():
    with pytest.raises(WorkspaceValidationError):
        validation.validate_description("y" * (validation.DESCRIPTION_MAX_LEN + 1))
    assert validation.validate_description(None) == ""


def test_color_validation():
    assert validation.validate_color("#ABCDEF") == "#abcdef"
    assert validation.validate_color("#abc") == "#abc"
    assert validation.validate_color(None) == "#6366f1"
    with pytest.raises(WorkspaceValidationError):
        validation.validate_color("blue")


def test_icon_validation():
    assert validation.validate_icon("🧠") == "🧠"
    assert validation.validate_icon(None) == "📁"
    with pytest.raises(WorkspaceValidationError):
        validation.validate_icon("x" * (validation.ICON_MAX_LEN + 1))


def test_name_compare_is_case_insensitive():
    assert validation.normalize_name_for_compare("Machine  Learning") == validation.normalize_name_for_compare(
        "machine learning"
    )
