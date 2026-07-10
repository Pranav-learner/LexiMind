"""Unit tests for token-aware conversation memory."""

from __future__ import annotations

from app.chat.memory import render_history, select_history


def _m(role, content):
    return {"role": role, "content": content}


def test_selects_recent_within_message_cap():
    msgs = [_m("user", f"message number {i}") for i in range(30)]
    out = select_history(msgs, token_budget=100000, max_messages=5)
    assert len(out) == 5
    # chronological order preserved, and it's the LAST 5.
    assert out[-1]["content"] == "message number 29"
    assert out[0]["content"] == "message number 25"


def test_token_budget_limits_selection():
    msgs = [_m("user", "word " * 50) for _ in range(10)]  # ~50+ tokens each
    out = select_history(msgs, token_budget=120, max_messages=100)
    # Budget should cut it well below all 10.
    assert 0 < len(out) < 10


def test_skips_empty_and_keeps_order():
    msgs = [_m("user", "hi"), _m("assistant", ""), _m("user", "there")]
    out = select_history(msgs, token_budget=1000, max_messages=10)
    assert [m["content"] for m in out] == ["hi", "there"]


def test_render_history_formats_roles():
    text = render_history([_m("user", "Q?"), _m("assistant", "A.")])
    assert "User: Q?" in text and "Assistant: A." in text


def test_empty_history():
    assert select_history([], token_budget=1000) == []
    assert render_history([]) == ""
