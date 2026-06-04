"""Unit tests for token counting + budget management."""

from app.context.budget import TokenBudgetManager
from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter, heuristic_token_count
from tests.test_context_helpers import mk


def test_heuristic_token_count_monotonic_and_zero():
    assert heuristic_token_count("") == 0
    assert heuristic_token_count("hello world") > 0
    assert heuristic_token_count("a b c d e f") >= heuristic_token_count("a b c")


def test_pluggable_counter():
    c = TokenCounter(count_fn=lambda t: len(t.split()))
    assert c.count("one two three") == 3
    assert c.count_many(["a b", "c"]) == 3


def test_available_context_subtracts_reserves():
    mgr = TokenBudgetManager(TokenCounter(lambda t: len(t.split())),
                             context_window=1000, system_reserve=100, response_reserve=200)
    plan = mgr.plan("a b c d e")  # 5 tokens user prompt
    assert plan.user_prompt_tokens == 5
    assert plan.available_context == 1000 - 100 - 200 - 5


def test_available_context_never_negative():
    mgr = TokenBudgetManager(TokenCounter(lambda t: len(t.split())),
                             context_window=50, system_reserve=100, response_reserve=200)
    assert mgr.plan("x").available_context == 0


def test_greedy_fit_drops_overflow_in_priority_order():
    mgr = TokenBudgetManager(TokenCounter(lambda t: len(t.split())), context_window=1000)
    ev = [Evidence.from_chunk(mk("a", "one two three")),   # 3
          Evidence.from_chunk(mk("b", "four five")),       # 2
          Evidence.from_chunk(mk("c", "six seven eight"))] # 3
    kept, dropped, used = mgr.greedy_fit(ev, available_tokens=5)
    assert [e.chunk_id for e in kept] == ["a", "b"]
    assert [e.chunk_id for e in dropped] == ["c"]
    assert used == 5
