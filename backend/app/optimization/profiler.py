"""Query profiler — deterministic complexity estimation (no LLM).

Estimates request complexity/quality-need from cheap signals (length, multi-part markers, question type,
research keywords). This drives adaptive pipeline selection (Step 9): a simple FAQ profiles low → cheap
model + small context; a research question profiles high → best model + graph + large context.
"""

from __future__ import annotations

import re
from typing import List

from app.optimization.interfaces import RequestProfile

_RESEARCH_MARKERS = ("compare", "contrast", "analyze", "evaluate", "synthesize", "relationship", "why",
                     "how does", "implications", "trade-off", "tradeoff", "across", "versus", " vs ")
_MULTI_MARKERS = (" and ", " or ", ";", "\n", " also ", " both ")


def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9']+", text.lower()) if len(w) > 2]


class QueryProfiler:
    def profile(self, query: str) -> RequestProfile:
        q = (query or "").strip()
        words = _tokenize(q)
        length_score = min(1.0, len(words) / 40.0)
        ql = q.lower()
        research_hits = sum(1 for m in _RESEARCH_MARKERS if m in ql)
        multi_hits = sum(1 for m in _MULTI_MARKERS if m in ql)
        research_score = min(1.0, research_hits / 3.0)
        multi_score = min(1.0, multi_hits / 3.0)

        complexity = round(min(1.0, 0.5 * length_score + 0.3 * research_score + 0.2 * multi_score), 3)
        tier = "simple" if complexity < 0.33 else ("complex" if complexity > 0.66 else "moderate")
        is_research = research_hits >= 1 and complexity >= 0.4

        # quality requirement scales with complexity + research intent
        quality_req = round(min(1.0, 0.4 + 0.4 * complexity + (0.2 if is_research else 0.0)), 3)
        est_context = int(800 + 2600 * complexity)          # simple ≈800, complex ≈3400 tokens
        est_output = int(200 + 700 * complexity)

        return RequestProfile(query=q, complexity=complexity, tier=tier, est_context_tokens=est_context,
                              est_output_tokens=est_output, quality_requirement=quality_req,
                              is_research=is_research, keywords=words[:12])
