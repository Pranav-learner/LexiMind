"""Multimodal context compression (Step 6) — shrink evidence to fit budget WITHOUT losing meaning.

Modality-aware, reusing Phase-2's heuristic token counter (never re-embeds; pure text ops):
- text / OCR : OCR cleanup (collapse whitespace/hyphenation) then keyword-dense sentence trimming.
- table      : summarize to headers + row count when the serialization is long.
- metadata   : prune to the title/name.
- image / diagram : captions are already terse; trim to the leading sentences if over budget.

Citation traceability is preserved (compression changes only `content`, never the citation). Critical
evidence is never dropped here — only condensed; dropping is the budget manager's decision.
"""

from __future__ import annotations

import re
from typing import List

from app.context.tokenizer import heuristic_token_count

_SENT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")
_HYPHEN = re.compile(r"(\w+)-\s+(\w+)")


def ocr_cleanup(text: str) -> str:
    text = _HYPHEN.sub(r"\1\2", text or "")   # join hyphenated line breaks
    return _WS.sub(" ", text).strip()


def _keyword_dense_sentences(text: str, keywords: List[str], target_tokens: int) -> str:
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    if not sents:
        return text
    kw = set(k.lower() for k in keywords)
    scored = sorted(
        enumerate(sents),
        key=lambda pair: (-sum(1 for k in kw if k in pair[1].lower()), pair[0]),
    )
    chosen, used = [], 0
    for idx, sent in scored:
        cost = heuristic_token_count(sent)
        if used + cost > target_tokens and chosen:
            break
        chosen.append((idx, sent))
        used += cost
    chosen.sort(key=lambda p: p[0])  # restore reading order
    return " ".join(s for _, s in chosen)


def compress(content: str, modality: str, target_tokens: int, keywords: List[str], metadata: dict | None = None) -> str:
    """Compress `content` for `modality` toward `target_tokens`. Returns the condensed text."""
    metadata = metadata or {}
    if heuristic_token_count(content) <= target_tokens:
        return content
    if modality == "table":
        headers = metadata.get("headers") or []
        n_rows = metadata.get("n_rows", 0)
        summary = f"Table with columns [{', '.join(str(h) for h in headers)}] and {n_rows} rows."
        return summary if heuristic_token_count(summary) <= target_tokens else summary[: target_tokens * 4]
    if modality == "metadata":
        return (content or "").split("\n")[0][: max(20, target_tokens * 4)]
    cleaned = ocr_cleanup(content) if modality in ("ocr", "text") else content
    return _keyword_dense_sentences(cleaned, keywords, target_tokens)
