"""Future-integration seams (Steps 14 & 15) — DECLARED interfaces, intentionally NOT wired.

This module does NOT perform retrieval and does NOT modify the Phase-1 Retrieval Engine, the Phase-2
Context Engineering Engine, or their Phase-4 multimodal evolutions. It only prepares typed adapters
so a FUTURE "Temporal Retrieval" module can plug media chunks into `app.mmretrieval` and a future
"Timeline-aware Context" step can plug temporal evidence into `app.mmcontext` WITHOUT reshaping this
module's storage.

Mirrors the pattern used by `app.mmretrieval` (`to_context_chunks`) and `app.ingestion`
(`MultimodalChunk.embedding_status="pending"`): the contract exists, the wiring is deferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---- temporal retrieval unit (what a future retriever would return) -------------------------
@dataclass
class TemporalUnit:
    """A retrievable temporal knowledge unit derived from a MediaChunk.

    `modality` matches the mmretrieval modality vocabulary so a future TemporalRetriever can emit
    `RetrievalHit`s that fuse cleanly with text/OCR/image/table hits.
    """
    chunk_id: str
    document_id: str
    workspace_id: str
    modality: str          # "transcript" | "scene" | "subtitle" | "ocr" | "frame" | "speaker"
    content: str
    start_ms: int
    end_ms: int
    speaker_id: Optional[str] = None
    scene_id: Optional[str] = None
    asset_id: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


def to_temporal_units(chunks: List[Any]) -> List[TemporalUnit]:
    """Adapt persisted `MediaChunk` rows into retrieval-ready `TemporalUnit`s. Interface only —
    no index is built or queried here. A future module calls this then embeds/indexes the result."""
    units: List[TemporalUnit] = []
    for c in chunks:
        units.append(TemporalUnit(
            chunk_id=c.id, document_id=c.document_id, workspace_id=c.workspace_id,
            modality=c.chunk_type, content=c.content, start_ms=c.start_ms, end_ms=c.end_ms,
            speaker_id=c.speaker_id, scene_id=c.scene_id, asset_id=c.asset_id, meta=c.meta,
        ))
    return units


# ---- context seam (what a future timeline-aware context step would consume) -----------------
def to_context_evidence(units: List[TemporalUnit]) -> List[Dict[str, Any]]:
    """Shape temporal units into the dict the Context Engineering Engine expects for evidence.

    Deliberately additive: it carries `start_ms`/`end_ms`/`speaker`/`modality` so a future
    timeline-aware assembler can cite "at 12:04, SPEAKER_01 said …" without changing existing
    citation preservation, dedup, ranking, compression, or assembly behaviour.
    """
    out: List[Dict[str, Any]] = []
    for u in units:
        out.append({
            "chunk_id": u.chunk_id, "document_id": u.document_id, "text": u.content,
            "modality": u.modality, "start_ms": u.start_ms, "end_ms": u.end_ms,
            "speaker_id": u.speaker_id, "scene_id": u.scene_id, "metadata": u.meta or {},
        })
    return out
