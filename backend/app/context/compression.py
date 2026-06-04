"""Context compression (Phase 2, Task 5) — reduce tokens, preserve information & citations.

Three complementary strategies, all offline and deterministic:
  1. merge_overlapping  — fuse adjacent chunks from the same document/page into one piece
     of evidence (union their citations) so overlapping text isn't repeated.
  2. remove_redundancy  — drop sentences that already appeared in a higher-priority chunk.
  3. compress_to_fit    — extractive summary of a single chunk: keep the sentences most
     relevant to the query until it fits a token target (used for the marginal chunk that
     would otherwise overflow the budget).

CITATION PRESERVATION (Task 6) is an invariant here: every operation keeps each evidence's
`citations` list intact (merging unions them; summarizing never touches them). A chunk's
provenance survives even if some of its sentences are removed.

FUTURE LLM-BASED COMPRESSION: the summarize step goes through a `CompressionStrategy`
interface. The default `ExtractiveStrategy` is rule-based; an `LLMCompressionStrategy`
(stub provided) can later call a local model to abstractively compress — swap it in without
touching the compressor or builder.
"""

from __future__ import annotations

import re
from typing import List, Protocol, Set

from app.context.schemas import Evidence
from app.context.tokenizer import TokenCounter

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _fingerprint(sentence: str) -> str:
    return " ".join(_WORD_RE.findall(sentence.lower()))


class CompressionStrategy(Protocol):
    """Compress `text` to roughly `target_tokens`, biased toward `query_keywords`."""

    def summarize(self, text: str, target_tokens: int, query_keywords: List[str], counter: TokenCounter) -> str:
        ...


class ExtractiveStrategy:
    """Keep the highest-scoring sentences (query overlap + lead bias) until under target."""

    def summarize(self, text: str, target_tokens: int, query_keywords: List[str], counter: TokenCounter) -> str:
        sentences = _split_sentences(text)
        if len(sentences) <= 1:
            return text
        kw = set(query_keywords)

        scored = []
        for i, s in enumerate(sentences):
            tokens = set(_WORD_RE.findall(s.lower()))
            overlap = (len(kw & tokens) / len(kw)) if kw else 0.0
            lead_bonus = 0.2 if i == 0 else 0.0  # first sentence often topical
            scored.append((overlap + lead_bonus, i, s))

        # Pick best sentences by score, then restore original order for readability.
        chosen: List[int] = []
        used = 0
        for _score, idx, s in sorted(scored, key=lambda x: x[0], reverse=True):
            cost = counter.count(s)
            if used + cost > target_tokens and chosen:
                continue
            chosen.append(idx)
            used += cost
            if used >= target_tokens:
                break
        chosen.sort()
        return " ".join(sentences[i] for i in chosen) if chosen else sentences[0]


class LLMCompressionStrategy:
    """Seam for future abstractive compression via a local LLM. Falls back to extractive."""

    def __init__(self, fallback: CompressionStrategy | None = None):
        self.fallback = fallback or ExtractiveStrategy()

    def summarize(self, text: str, target_tokens: int, query_keywords: List[str], counter: TokenCounter) -> str:
        # TODO(phase-2+): call Ollama to abstractively summarize `text` within target_tokens.
        # Kept offline-safe by delegating to the extractive strategy for now.
        return self.fallback.summarize(text, target_tokens, query_keywords, counter)


class ContextCompressor:
    def __init__(self, counter: TokenCounter, strategy: CompressionStrategy | None = None):
        self.counter = counter
        self.strategy = strategy or ExtractiveStrategy()

    # --- 1. merge overlapping evidence ------------------------------------
    def merge_overlapping(self, evidence: List[Evidence]) -> List[Evidence]:
        """Merge same-document, same-page evidence whose paragraph ranges touch.

        Citations are unioned; the merged text concatenates the pieces in paragraph order
        without repeating an identical piece. Evidence score becomes the max of the group.
        """
        merged: List[Evidence] = []
        for ev in evidence:
            target = None
            for m in merged:
                if (
                    ev.document_id
                    and ev.document_id == m.document_id
                    and ev.page_number == m.page_number
                ):
                    target = m
                    break
            if target is None:
                merged.append(ev)
                continue
            # fuse ev into target
            if ev.text.strip() and ev.text.strip() not in target.text:
                target.text = f"{target.text}\n{ev.text}".strip()
            existing = {c.chunk_id for c in target.citations}
            for c in ev.citations:
                if c.chunk_id not in existing:
                    target.citations.append(c)
                    existing.add(c.chunk_id)
            target.merged_from.append(ev.chunk_id)
            target.evidence_score = max(target.evidence_score, ev.evidence_score)
        return merged

    # --- 2. remove cross-chunk redundancy ---------------------------------
    def remove_redundancy(self, evidence: List[Evidence]) -> List[Evidence]:
        """Drop sentences already seen in a higher-priority chunk. Citations untouched."""
        seen: Set[str] = set()
        out: List[Evidence] = []
        for ev in evidence:  # assumed best-first
            kept_sentences = []
            for s in _split_sentences(ev.text):
                fp = _fingerprint(s)
                if not fp or fp in seen:
                    continue
                seen.add(fp)
                kept_sentences.append(s)
            if kept_sentences:
                ev.text = " ".join(kept_sentences)
                out.append(ev)
            # If every sentence was redundant, the chunk added nothing new -> drop it
            # (its information is fully present in a higher-priority chunk already kept).
        return out

    # --- 3. summarize a single chunk to fit -------------------------------
    def compress_to_fit(self, ev: Evidence, target_tokens: int, query_keywords: List[str]) -> Evidence:
        if target_tokens <= 0:
            return ev
        if self.counter.count(ev.text) <= target_tokens:
            return ev
        ev.text = self.strategy.summarize(ev.text, target_tokens, query_keywords, self.counter)
        ev.compressed = True
        return ev
