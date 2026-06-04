"""LexiMind context engineering engine (Phase 2).

Turns raw retrieved chunks into the most useful, lowest-token context for the LLM:

    Retrieved Chunks
      -> Duplicate Detection   (dedup.py)
      -> Evidence Ranking      (ranking.py)
      -> Token Budgeting       (budget.py)
      -> Context Compression   (compression.py)
      -> Context Assembly      (assembly.py)
      -> LLM

`ContextBuilderService` (builder.py) is the single orchestrator; everything downstream
(the /query route, future agents) depends only on it.
"""

from app.context.builder import ContextBuilderService
from app.context.schemas import Citation, ContextResult, Evidence

__all__ = ["ContextBuilderService", "ContextResult", "Evidence", "Citation"]
