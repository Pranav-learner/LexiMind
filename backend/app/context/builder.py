"""ContextBuilderService (Phase 2, Task 1) — the context engine orchestrator.

    Retrieved Chunks
      -> Evidence Ranking      (so dedup keeps the strongest version)
      -> Duplicate Detection
      -> Compression: merge overlaps + remove cross-chunk redundancy
      -> Token Budgeting       (greedy fit; marginal chunk compressed to fit)
      -> Context Assembly
      -> ContextResult { context, evidence, citations, metrics }

NOTE on stage order: the Phase-2 spec lists Dedup before Ranking. We rank FIRST on purpose
— dedup must keep the *highest-quality* version of a duplicate pair, which requires the
blended evidence score to already exist. This is the one deliberate (documented) deviation
from the listed order; the conceptual stages are otherwise identical.

This is the single entry point the /query route and future agents call. Models load lazily
elsewhere; this service itself does no I/O and is fully unit-testable.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from app.context.assembly import ContextAssembler, _citation_label
from app.context.budget import TokenBudgetManager
from app.context.compression import ContextCompressor
from app.context.dedup import DuplicateChunkDetector
from app.context.metrics import compute_metrics
from app.context.ranking import EvidenceRanker
from app.context.schemas import ContextResult, Evidence
from app.context.tokenizer import TokenCounter
from app.retrieval.schemas import RetrievedChunk

_WORD_RE = re.compile(r"[a-z0-9]+")


class ContextBuilderService:
    def __init__(
        self,
        *,
        counter: Optional[TokenCounter] = None,
        ranker: Optional[EvidenceRanker] = None,
        deduper: Optional[DuplicateChunkDetector] = None,
        compressor: Optional[ContextCompressor] = None,
        assembler: Optional[ContextAssembler] = None,
        context_window: int = 8192,
        system_reserve: int = 500,
        response_reserve: int = 1000,
        dedup_threshold: float = 0.85,
        enable_compression: bool = True,
    ):
        self.counter = counter or TokenCounter()
        self.ranker = ranker or EvidenceRanker()
        self.deduper = deduper or DuplicateChunkDetector(threshold=dedup_threshold)
        self.compressor = compressor or ContextCompressor(self.counter)
        self.assembler = assembler or ContextAssembler()
        self.budget = TokenBudgetManager(
            self.counter,
            context_window=context_window,
            system_reserve=system_reserve,
            response_reserve=response_reserve,
        )
        self.enable_compression = enable_compression

    def build(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        *,
        query_keywords: Optional[Sequence[str]] = None,
        user_prompt: Optional[str] = None,
    ) -> ContextResult:
        keywords = list(query_keywords) if query_keywords is not None else _WORD_RE.findall((query or "").lower())

        evidence: List[Evidence] = [Evidence.from_chunk(c) for c in chunks]
        num_input_chunks = len(evidence)
        raw_tokens = self.counter.count_many([e.text for e in evidence])

        if not evidence:
            return ContextResult(context="", evidence=[], citations=[], metrics=compute_metrics(
                evidence=[], context_text="", query_keywords=keywords, raw_tokens=0,
                final_tokens=0, num_input_chunks=0, num_duplicates_removed=0, counter=self.counter,
            ))

        # 1. Rank (sets evidence_score, sorts best-first)
        evidence = self.ranker.rank(evidence, keywords)

        # 2. Deduplicate (keeps the strongest version of each duplicate)
        evidence, removed = self.deduper.detect(evidence)
        evidence.sort(key=lambda e: e.evidence_score, reverse=True)  # detect() returned quality order
        num_duplicates_removed = len(removed)

        # 3. Compression — merge overlaps, then strip cross-chunk redundancy
        if self.enable_compression:
            evidence = self.compressor.merge_overlapping(evidence)
            evidence = self.compressor.remove_redundancy(evidence)
            evidence.sort(key=lambda e: e.evidence_score, reverse=True)

        # 4. Token budgeting — greedy fit in priority order. We budget on the RENDERED
        # block size (citation header + text), matching what the assembler emits, so the
        # final context provably fits the window.
        plan = self.budget.plan(user_prompt if user_prompt is not None else query)
        available = plan.available_context
        kept, dropped, used = self.budget.greedy_fit(evidence, available, cost_fn=self._block_cost)

        # 4b. Try to rescue the strongest dropped evidence by compressing it to fit.
        if self.enable_compression and dropped:
            for ev in dropped:
                remaining = available - used
                header = self._header_cost(ev)
                if remaining - header <= 0:
                    break
                ev = self.compressor.compress_to_fit(ev, remaining - header, keywords)
                cost = self._block_cost(ev)
                if cost <= remaining and ev.text.strip():
                    kept.append(ev)
                    used += cost

        # 5. Assemble
        context_text, citations = self.assembler.assemble(kept)

        metrics = compute_metrics(
            evidence=kept,
            context_text=context_text,
            query_keywords=keywords,
            raw_tokens=raw_tokens,
            final_tokens=self.counter.count(context_text),
            num_input_chunks=num_input_chunks,
            num_duplicates_removed=num_duplicates_removed,
            counter=self.counter,
        )
        metrics["available_context_budget"] = available
        metrics["user_prompt_tokens"] = plan.user_prompt_tokens

        return ContextResult(context=context_text, evidence=kept, citations=citations, metrics=metrics)

    # --- budgeting helpers: estimate the assembler's rendered cost per evidence -------
    def _header_cost(self, ev: Evidence) -> int:
        # Mirrors ContextAssembler's block header `[n] <label>\n` (n is ~1 token).
        return self.counter.count(f"[0] {_citation_label(ev.citations[0])}\n")

    def _block_cost(self, ev: Evidence) -> int:
        return self._header_cost(ev) + self.counter.count(ev.text)
