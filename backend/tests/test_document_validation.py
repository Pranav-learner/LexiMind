"""Unit tests for document field/file validation (pure functions, no I/O)."""

from __future__ import annotations

import pytest

from app.documents import validation
from app.documents.errors import (
    DocumentValidationError,
    FileTooLarge,
    UnsupportedFileType,
)


def test_display_name_defaults_to_filename_when_blank():
    assert validation.validate_display_name(None, fallback="report.pdf") == "report.pdf"
    assert validation.validate_display_name("   ", fallback="report.pdf") == "report.pdf"


def test_display_name_collapses_whitespace_and_trims():
    assert validation.validate_display_name("  My   Notes  ", fallback="x") == "My Notes"


def test_display_name_too_long_rejected():
    with pytest.raises(DocumentValidationError):
        validation.validate_display_name("a" * 301, fallback="x")


def test_display_name_forbidden_and_control_chars_rejected():
    with pytest.raises(DocumentValidationError):
        validation.validate_display_name("bad/name", fallback="x")
    with pytest.raises(DocumentValidationError):
        validation.validate_display_name("bad\x01name", fallback="x")


def test_description_capped():
    assert validation.validate_description(None) == ""
    assert validation.validate_description("  hi  ") == "hi"
    with pytest.raises(DocumentValidationError):
        validation.validate_description("a" * 4001)


def test_sanitize_filename_strips_path_and_forbidden():
    assert validation.sanitize_filename("../../etc/passwd") == "passwd"
    # basename splits only on "/" (posix); the remaining \\ : ? are stripped as forbidden.
    assert validation.sanitize_filename("a/b\\c:name?.pdf") == "bcname.pdf"
    assert validation.sanitize_filename("   ") == "untitled"
    assert validation.sanitize_filename("") == "untitled"


def test_file_extension_and_type():
    assert validation.file_extension("Report.PDF") == "pdf"
    assert validation.file_extension("noext") == ""
    assert validation.validate_file_type("Report.PDF") == "pdf"
    with pytest.raises(UnsupportedFileType):
        validation.validate_file_type("malware.exe")
    with pytest.raises(UnsupportedFileType):
        validation.validate_file_type("noext")


def test_mime_for():
    assert validation.mime_for("pdf") == "application/pdf"
    assert validation.mime_for("unknownext") == "application/octet-stream"


def test_file_size_bounds():
    assert validation.validate_file_size(100) == 100
    with pytest.raises(DocumentValidationError):
        validation.validate_file_size(0)
    with pytest.raises(FileTooLarge):
        validation.validate_file_size(10**12)  # 1 TB > 50 MB default


def test_guess_language_and_word_count():
    assert validation.guess_language("The quick brown fox jumps over the lazy dog") == "en"
    assert validation.guess_language("") == "unknown"
    assert validation.count_words("one two   three\nfour") == 4


def test_normalize_name_for_compare_is_case_insensitive():
    assert validation.normalize_name_for_compare("  My  File ") == validation.normalize_name_for_compare("my file")
