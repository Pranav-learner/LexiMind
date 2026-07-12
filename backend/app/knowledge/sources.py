"""Cross-modal knowledge sources (Step 7) — collect text to extract from, REUSING existing pipelines.

Graph construction never re-processes documents: it reads the text the ingestion / media / vision
pipelines already produced (MultimodalChunk.content across text/ocr/table/figure/image, MediaChunk.content
and TranscriptSegment.text for audio/video, plus the document title/description). Every modality feeds
the SAME graph. A `TextSource` carries the text + its provenance ref so entities/edges stay traceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from sqlalchemy.orm import Session


@dataclass
class TextSource:
    text: str
    source_ref: Dict[str, Any]   # {document_id, chunk_id, source_type}


def _ref(document_id: str, chunk_id, source_type: str) -> Dict[str, Any]:
    return {"document_id": document_id, "chunk_id": chunk_id, "source_type": source_type}


def collect_document_sources(db: Session, document) -> List[TextSource]:
    """All extractable text for one document/recording, across modalities (reuses existing chunk tables)."""
    out: List[TextSource] = []
    doc_id = document.id

    title = (document.display_name or document.filename or "").strip()
    desc = (document.description or "").strip()
    header = " ".join(x for x in (title, desc) if x)
    if header:
        out.append(TextSource(header, _ref(doc_id, None, "metadata")))

    # ingestion multimodal chunks (text / ocr / table / figure / image captions)
    try:
        from app.ingestion.repository import IngestionRepository
        for c in IngestionRepository(db).chunks_for(doc_id):
            if (c.content or "").strip():
                out.append(TextSource(c.content, _ref(doc_id, c.id, c.chunk_type)))
    except Exception:
        pass

    # media (audio/video): transcript segments + media chunks
    if getattr(document, "media_type", "document") in ("audio", "video"):
        try:
            from app.media.repository import MediaRepository
            mr = MediaRepository(db)
            for seg in mr.segments_for(doc_id):
                if (seg.text or "").strip():
                    out.append(TextSource(seg.text, _ref(doc_id, seg.id, "transcript")))
            for mc in mr.chunks_for(doc_id):
                if (mc.content or "").strip():
                    out.append(TextSource(mc.content, _ref(doc_id, mc.id, mc.chunk_type)))
        except Exception:
            pass

    return out


def count_document_sources(db: Session, document) -> int:
    """Cheap-ish source count for the incremental staleness guard (mirrors citations.ensure_synced)."""
    return len(collect_document_sources(db, document))
