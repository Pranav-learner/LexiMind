"""LLM-as-a-Judge (Step 6) — an ADDITIONAL qualitative signal, never a replacement for objective metrics.

Reuses the SINGLE `answer_fn` (AnswerService) — no new LLM pipeline — to score an answer on quality /
completeness / relevance / citation quality, and to compare two answers (A/B, model-vs-model,
prompt-vs-prompt). The model's reply is parsed DETERMINISTICALLY (regex for `dimension: score`), so a
malformed judgment degrades to a neutral score rather than crashing. Judging is opt-in per run.
"""

from __future__ import annotations

import re
from typing import Optional

from app.evaluation.interfaces import EvalItemInput, Judgment, PipelineOutput

_DIMENSIONS = ("quality", "completeness", "relevance", "citation")
_SCORE_LINE = re.compile(r"(quality|completeness|relevance|citation)\s*[:=]\s*([0-9](?:\.\d+)?)", re.I)

_JUDGE_SYSTEM = (
    "You are a strict answer-quality judge. Score the assistant answer to the user question on these "
    "dimensions from 1 (poor) to 5 (excellent): quality, completeness, relevance, citation. Consider the "
    "reference answer and evidence if provided. Respond with EXACTLY four lines of `dimension: score` and "
    "one short reason line. Do not reveal step-by-step reasoning."
)

_COMPARE_SYSTEM = (
    "You are comparing two assistant answers (A and B) to the same question. Decide which is better "
    "overall on quality, completeness, relevance and grounding. Respond with `winner: A` or `winner: B` "
    "or `winner: tie`, then one short reason line. Do not reveal step-by-step reasoning."
)


class LLMJudge:
    name = "llm-judge-v1"

    def judge(self, item: EvalItemInput, output: PipelineOutput, *, answer_fn=None) -> Judgment:
        if answer_fn is None or not output.answer:
            return Judgment(scores={d: 0.0 for d in _DIMENSIONS}, overall=0.0, rationale="no judge/answer")
        ref = f"\nReference answer: {item.expected_answer}" if item.expected_answer else ""
        prompt = (f"{_JUDGE_SYSTEM}\n\nQuestion: {item.question}{ref}\n\nAssistant answer:\n"
                  f"{output.answer[:3000]}\n\nScores:\n")
        try:
            raw = (answer_fn(prompt) or "")
        except Exception:
            raw = ""
        scores = {}
        for m in _SCORE_LINE.finditer(raw):
            scores[m.group(1).lower()] = min(1.0, float(m.group(2)) / 5.0)   # normalize 1..5 → 0..1
        for d in _DIMENSIONS:
            scores.setdefault(d, 0.6)   # neutral default when the judge omitted a dimension
        overall = round(sum(scores.values()) / len(scores), 6)
        reason = next((l.strip() for l in raw.splitlines() if l.strip() and ":" not in l[:14]), "")
        return Judgment(scores=scores, overall=overall, rationale=reason[:400])

    def compare(self, item: EvalItemInput, a: PipelineOutput, b: PipelineOutput, *,
                answer_fn=None) -> str:
        """Return 'A' | 'B' | 'tie' for a head-to-head answer comparison."""
        if answer_fn is None:
            return "tie"
        prompt = (f"{_COMPARE_SYSTEM}\n\nQuestion: {item.question}\n\nAnswer A:\n{a.answer[:2000]}\n\n"
                  f"Answer B:\n{b.answer[:2000]}\n\nVerdict:\n")
        try:
            raw = (answer_fn(prompt) or "").lower()
        except Exception:
            return "tie"
        m = re.search(r"winner\s*[:=]\s*(a|b|tie)", raw)
        return m.group(1).upper() if m and m.group(1) != "tie" else "tie"
