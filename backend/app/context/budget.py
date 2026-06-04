"""Token budget management (Phase 2, Task 4).

Guarantees the assembled context never overflows the model's context window. The window
is partitioned up front:

    context_window
      = system_prompt_reserve            (instructions / role)
      + user_prompt_tokens               (the question, measured)
      + response_reserve                 (room for the answer to be generated)
      + available_context_budget         (what's left for retrieved evidence)  <-- managed here

If retrieved evidence exceeds the available budget, lower-priority evidence is dropped (or,
upstream, compressed) so the prompt always fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter


@dataclass(frozen=True)
class Budget:
    context_window: int
    system_reserve: int
    user_prompt_tokens: int
    response_reserve: int

    @property
    def available_context(self) -> int:
        """Tokens left for retrieved evidence (never negative)."""
        return max(
            0,
            self.context_window
            - self.system_reserve
            - self.user_prompt_tokens
            - self.response_reserve,
        )


class TokenBudgetManager:
    def __init__(
        self,
        counter: TokenCounter,
        *,
        context_window: int = 8192,
        system_reserve: int = 500,
        response_reserve: int = 1000,
    ):
        self.counter = counter
        self.context_window = context_window
        self.system_reserve = system_reserve
        self.response_reserve = response_reserve

    def plan(self, user_prompt: str) -> Budget:
        return Budget(
            context_window=self.context_window,
            system_reserve=self.system_reserve,
            user_prompt_tokens=self.counter.count(user_prompt),
            response_reserve=self.response_reserve,
        )

    def greedy_fit(
        self,
        evidence: List[Evidence],
        available_tokens: int,
        *,
        cost_fn: Optional[Callable[[Evidence], int]] = None,
    ) -> Tuple[List[Evidence], List[Evidence], int]:
        """Keep evidence in priority order until the budget is exhausted.

        Evidence must already be sorted best-first (EvidenceRanker does this). `cost_fn`
        lets the caller budget on the *rendered* block size (text + citation header) so
        the assembled context truly fits the window — defaults to the raw text cost.
        Returns (kept, dropped, tokens_used). A single item larger than the whole budget
        is dropped here; the builder may instead hand it to the compressor first.
        """
        cost_fn = cost_fn or (lambda e: self.counter.count(e.text))
        kept: List[Evidence] = []
        dropped: List[Evidence] = []
        used = 0
        for ev in evidence:
            cost = cost_fn(ev)
            if used + cost <= available_tokens:
                kept.append(ev)
                used += cost
            else:
                dropped.append(ev)
        return kept, dropped, used
