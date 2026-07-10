"""Unit tests for chat validation (pure)."""

from __future__ import annotations

import pytest

from app.chat import validation
from app.chat.errors import ChatValidationError


def test_title_defaults_and_normalizes():
    assert validation.validate_title(None) == validation.DEFAULT_TITLE
    assert validation.validate_title("   ") == validation.DEFAULT_TITLE
    assert validation.validate_title("  My   Chat ") == "My Chat"


def test_title_length_and_control_chars():
    with pytest.raises(ChatValidationError):
        validation.validate_title("a" * 301)
    with pytest.raises(ChatValidationError):
        validation.validate_title("bad\x01title")


def test_description():
    assert validation.validate_description(None) == ""
    assert validation.validate_description("  hi ") == "hi"
    with pytest.raises(ChatValidationError):
        validation.validate_description("a" * 2001)


def test_message_content_required_and_capped():
    with pytest.raises(ChatValidationError):
        validation.validate_message_content("   ")
    assert validation.validate_message_content("  hello ") == "hello"
    with pytest.raises(ChatValidationError):
        validation.validate_message_content("a" * 32001)


def test_title_from_message():
    assert validation.title_from_message("What is paging in operating systems?") == "What is paging in operating systems?"
    long = "word " * 40
    out = validation.title_from_message(long)
    assert len(out) <= 61 and out.endswith("…")
    assert validation.title_from_message("") == validation.DEFAULT_TITLE
