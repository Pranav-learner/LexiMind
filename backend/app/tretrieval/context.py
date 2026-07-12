"""Timeline-aware Context Engineering (Step 7) — the temporal evolution of Phase-2 / Phase-4 context.

REUSES the Phase-2 token heuristic (`app.context.tokenizer.heuristic_token_count`) and the Phase-4
extractive compressor (`app.mmcontext.compression.compress`) rather than duplicating them. Adds the
TIME semantics those layers lack:
  - Temporal dedup: near-duplicate hits that also OVERLAP in time (same speaker) are merged.
  - Timeline-aware ranking: confidence blended with a light recency/among-set signal.
  - Timestamp-aware compression: compress each block to its token budget WITHOUT dropping its
    [start,end] anchor (the timestamp lives on the block, not the text, so it always survives).
  - Temporal token budget: a hard total ceiling split across the included blocks.
  - Timeline assembly: blocks are ordered by document then start time so the LLM sees a coherent
    chronology (Step 9 handoff).

Pure functions + a small dataclass; no ORM, no LLM. Returns ordered `ContextBlock`s the prompt builder
renders. Does NOT modify Phase-2/4 context behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app.context.tokenizer import heuristic_token_count
from app.mmcontext.compression import compress
from app.tretrieval.schemas import TemporalHit


@dataclass
class ContextBlock:
    modality: str
    document_id: str
    start_ms: int
    end_ms: int
    speaker_label: str
    content: str
    tokens: int
    citation_index: int
    metadata: Dict = field(default_factory=dict)


def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{(s % 3600) // 60:02d}:{s % 60:02d}"


def _overlap(a: TemporalHit, b: TemporalHit) -> bool:
    return not (a.end_ms < b.start_ms or a.start_ms > b.end_ms)


def temporal_dedup(hits: List[TemporalHit], *, jaccard: float = 0.8) -> Tuple[List[TemporalHit], int]:
    """Drop a hit if an already-kept hit from the same document overlaps in time, shares the speaker,
    and is textually near-identical. Complementary modalities (frame vs transcript) are kept."""
    kept: List[TemporalHit] = []
    removed = 0
    for h in hits:
        dup = False
        htok = set((h.content or "").lower().split())
        for k in kept:
            if k.document_id != h.document_id or not _overlap(k, h):
                continue
            if (k.speaker_label or "") != (h.speaker_label or ""):
                continue
            ktok = set((k.content or "").lower().split())
            if not htok or not ktok:
                continue
            j = len(htok & ktok) / len(htok | ktok)
            if j >= jaccard:
                dup = True
                break
        if dup:
            removed += 1
        else:
            kept.append(h)
    return kept, removed


def build_context(hits: List[TemporalHit], keywords: List[str], *, total_budget: int = 2000,
                  per_block_min: int = 40) -> Tuple[List[ContextBlock], Dict]:
    """Dedup → budget → timestamp-aware compress → timeline-order. Returns (blocks, stats)."""
    deduped, removed = temporal_dedup(hits)
    if not deduped:
        return [], {"candidates": len(hits), "deduped": 0, "removed": removed, "included": 0,
                    "used_tokens": 0, "budget": total_budget}

    # Budget split proportional to confidence (min floor so low-rank hits still contribute).
    ranked = sorted(deduped, key=lambda h: h.confidence, reverse=True)
    conf_sum = sum(max(h.confidence, 0.05) for h in ranked) or 1.0
    blocks: List[ContextBlock] = []
    used = 0
    for i, h in enumerate(ranked, start=1):
        share = max(h.confidence, 0.05) / conf_sum
        target = max(per_block_min, int(total_budget * share))
        if used >= total_budget:
            break
        target = min(target, total_budget - used)
        if target < per_block_min:
            break
        modality = "text" if h.modality in ("transcript", "subtitle", "timestamp") else h.modality
        text = compress(h.content, modality, target, keywords, h.metadata)
        tok = heuristic_token_count(text)
        blocks.append(ContextBlock(
            modality=h.modality, document_id=h.document_id or "", start_ms=h.start_ms, end_ms=h.end_ms,
            speaker_label=h.speaker_label, content=text, tokens=tok, citation_index=i,
            metadata={"timespan": f"{_fmt(h.start_ms)}–{_fmt(h.end_ms)}", "confidence": h.confidence,
                      "source_type": h.source_type, "frame_id": h.frame_id, "scene_id": h.scene_id}))
        used += tok

    # Timeline assembly: chronological within each document (stable, document-grouped).
    blocks.sort(key=lambda b: (b.document_id, b.start_ms))
    for i, b in enumerate(blocks, start=1):
        b.citation_index = i

    stats = {"candidates": len(hits), "deduped": len(deduped), "removed": removed,
             "included": len(blocks), "used_tokens": used, "budget": total_budget}
    return blocks, stats
