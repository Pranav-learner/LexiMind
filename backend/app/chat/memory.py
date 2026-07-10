"""Conversation memory — token-aware selection of prior turns.

The message pipeline grounds retrieval in the *current* user message (documents), and gives the
LLM recent conversation history for continuity. This module decides WHICH prior turns to include
so the prompt never blows the model's context window.

Pure and dependency-light: it reuses the Phase-2 heuristic token counter (no faiss/torch) and is
trivially unit-testable. Conversation *summaries* (folding older turns into a synopsis) are a
future module; the seam is `summarize_older` below, currently a no-op placeholder.
"""

from __future__ import annotations

from typing import Any, Dict, List

try:  # reuse the Phase-2 estimator when available
    from app.context.tokenizer import heuristic_token_count as _tok
except Exception:  # pragma: no cover - defensive fallback
    def _tok(text: str) -> int:
        return max(1, len(text or "") // 4)


def _as_dict(m: Any) -> Dict[str, Any]:
    if isinstance(m, dict):
        return {"role": m.get("role"), "content": m.get("content", "")}
    return {"role": getattr(m, "role", None), "content": getattr(m, "content", "") or ""}


def select_history(
    messages: List[Any],
    *,
    token_budget: int = 1500,
    max_messages: int = 20,
) -> List[Dict[str, Any]]:
    """Return the most recent turns that fit the budget, in chronological order.

    `messages` are prior turns oldest→newest (Message rows or {role, content} dicts). Selection
    walks from the newest backwards, accumulating estimated tokens, and stops at whichever limit
    (token_budget or max_messages) is hit first. The result is re-ordered oldest→newest so it
    reads naturally in the prompt.
    """
    selected: List[Dict[str, Any]] = []
    used = 0
    for m in reversed(messages):
        d = _as_dict(m)
        if not d["content"]:
            continue
        cost = _tok(d["content"]) + 4  # +role/formatting overhead
        if selected and (used + cost > token_budget or len(selected) >= max_messages):
            break
        selected.append(d)
        used += cost
    selected.reverse()
    return selected


def render_history(history: List[Dict[str, Any]]) -> str:
    """Render selected turns as a compact transcript block for the LLM prompt."""
    lines = []
    for turn in history:
        who = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {turn.get('content', '').strip()}")
    return "\n".join(lines)


def summarize_older(messages: List[Any]) -> str:
    """Placeholder seam for a future summarization module.

    When conversations grow beyond the token budget, older turns will be folded into a running
    summary here instead of being dropped. For now it returns "" (no summary), so behavior is a
    pure sliding window over recent turns.
    """
    return ""
