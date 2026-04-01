"""Tests for export filename safety and unhandled error message sanitization."""

from ai_reo.api.routes import _ascii_filename_fragment, _content_disposition_filename
from ai_reo.main import _safe_exception_message


def test_ascii_filename_fragment_removes_unicode() -> None:
    raw = "[AutoRun] CTF Level 5 - 2026-04-01 10:05 -- test \u2014 \uc608\uc2dc"
    safe = _ascii_filename_fragment(raw)

    assert safe
    assert " " not in safe
    assert "\u2014" not in safe
    assert "\uc608" not in safe


def test_content_disposition_includes_ascii_and_utf8_filename() -> None:
    header = _content_disposition_filename("Session \u2014 \u2603")

    assert 'attachment; filename="ai-reo_' in header
    assert "filename*=UTF-8''" in header
    assert "%E2%80%94" in header


def test_safe_exception_message_ascii_fallback() -> None:
    exc = RuntimeError("failure \u2014 non ascii")
    message = _safe_exception_message(exc)

    assert "failure" in message
    assert "?" in message
