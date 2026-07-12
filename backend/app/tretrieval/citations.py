"""Temporal citations (Step 10) — timestamp/speaker/scene/frame-preserving citations.

Builds citation records from the assembled context blocks so every claim the LLM makes can point back
to a precise moment (document + [start,end] + speaker + scene/frame). This mirrors the existing
Citation Intelligence shape (index → source) but carries TIME, so the frontend can "open media → jump
to timestamp → highlight transcript → show speaker → show frame".
"""

from __future__ import annotations

from typing import Dict, List

from app.tretrieval.context import ContextBlock


def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{(s % 3600) // 60:02d}:{s % 60:02d}"


def build_citations(blocks: List[ContextBlock]) -> List[Dict]:
    out: List[Dict] = []
    for b in blocks:
        out.append({
            "index": b.citation_index,
            "document_id": b.document_id,
            "modality": b.modality,
            "start_ms": b.start_ms,
            "end_ms": b.end_ms,
            "timespan": f"{_fmt(b.start_ms)}–{_fmt(b.end_ms)}",
            "speaker_label": b.speaker_label,
            "scene_id": b.metadata.get("scene_id"),
            "frame_id": b.metadata.get("frame_id"),
            "text": b.content[:280],
        })
    return out
