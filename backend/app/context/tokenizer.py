"""Token counting.

WHY a pluggable counter (not just len()):
- The LLM is Ollama `llama3`, whose exact tokenizer isn't available offline as a Python
  package. Rather than couple the budgeter to one model, `TokenCounter` wraps a
  count-function. The default is a fast, model-agnostic heuristic; a precise tokenizer
  (tiktoken / a llama tokenizer) can be injected later with zero call-site changes.

The heuristic blends two signals that bracket real tokenization for English + code:
  - ~4 characters per token (OpenAI's well-known rule of thumb), and
  - ~1.3 tokens per whitespace word (sub-word splitting of longer words).
We take the max so we never *under*-estimate (under-estimating risks context overflow,
the one failure the budgeter exists to prevent).
"""

from __future__ import annotations

import math
import re
from typing import Callable, Optional

_WORD_RE = re.compile(r"\S+")


def heuristic_token_count(text: str) -> int:
    if not text:
        return 0
    chars = len(text)
    words = len(_WORD_RE.findall(text))
    by_chars = math.ceil(chars / 4)
    by_words = math.ceil(words * 1.3)
    return max(by_chars, by_words)


class TokenCounter:
    def __init__(self, count_fn: Optional[Callable[[str], int]] = None):
        self._count_fn = count_fn or heuristic_token_count

    def count(self, text: str) -> int:
        return self._count_fn(text or "")

    def count_many(self, texts) -> int:
        return sum(self.count(t) for t in texts)
