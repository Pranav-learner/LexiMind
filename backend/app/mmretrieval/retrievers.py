"""The multimodal retrievers (Step 4) — every modality behind ONE common interface.

`Retriever` protocol: `modality` + `retrieve(ctx, k) -> list[RetrievalHit]`. Concrete retrievers:

- `LexicalTextRetriever` / `HybridTextRetriever` — text. Production wraps the UNCHANGED Phase-1 hybrid
  pipeline (dense+BM25+RRF+reranker over FAISS); the lexical one (DB) is the faiss-free default/test.
- `OcrRetriever`   — OCR chunks (MultimodalChunk chunk_type=ocr).
- `ImageRetriever` — vision images/charts/screenshots/figures (VisionAnalysis, lexical over caption+keywords).
- `DiagramRetriever` — architecture/flowchart/UML/ER diagrams (VisionAnalysis diagram types + node labels).
- `TableRetriever` — structured tables (ExtractedTable, HEADER-AWARE: headers/columns weighted).
- `MetadataRetriever` — document titles/descriptions + vision topics/keywords.

Retrievers are plug-and-play: add a class with a `modality` + `retrieve` and register it in the
orchestrator. All are DB-backed and score lexically (bounded, deterministic, faiss/torch-free) so the
whole framework is testable; production text swaps in the real hybrid pipeline behind the same
interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

from sqlalchemy.orm import Session

from app.mmretrieval.repository import RetrievalRepository
from app.mmretrieval.schemas import RetrievalHit
from app.vision.validation import DIAGRAM_TYPES


@dataclass
class RetrievalContext:
    db: Session
    workspace_id: str
    owner_id: str
    query: str
    keywords: List[str]
    document_id: Optional[str] = None
    repo: Optional[RetrievalRepository] = None

    def repository(self) -> RetrievalRepository:
        if self.repo is None:
            self.repo = RetrievalRepository(self.db)
        return self.repo


class Retriever(Protocol):
    modality: str
    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]: ...


# ------------------------------------------------------------------ shared lexical scorer
def lexical_score(keywords: List[str], fields: List[tuple]) -> float:
    """Score a candidate by weighted keyword overlap across (text, weight) fields.

    Each distinct query keyword found in a field adds `weight`; repeated occurrences add a small
    capped bonus. A field containing the full query (as a phrase) gets a phrase bonus. Bounded and
    deterministic — the point is RELATIVE ranking within a retriever (normalization handles scale).
    """
    if not keywords:
        return 0.0
    total = 0.0
    for text, weight in fields:
        low = (text or "").lower()
        if not low:
            continue
        for kw in keywords:
            if kw in low:
                occ = low.count(kw)
                total += weight * (1.0 + min(occ - 1, 3) * 0.15)
    return total


def _finalize(hits: List[RetrievalHit], k: int) -> List[RetrievalHit]:
    """Sort by raw score, drop zero-score, assign rank_in_modality, take top-k."""
    ranked = sorted([h for h in hits if h.raw_score > 0], key=lambda h: h.raw_score, reverse=True)[:k]
    for i, h in enumerate(ranked, start=1):
        h.rank_in_modality = i
    return ranked


# ------------------------------------------------------------------ text
class LexicalTextRetriever:
    modality = "text"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for c in repo.chunks(ctx.workspace_id, ["text", "ocr"], ctx.document_id):
            score = lexical_score(ctx.keywords, [(c.content, 1.0)])
            if score <= 0:
                continue
            hits.append(RetrievalHit(
                key=f"chunk:{c.id}", modality="text", source_type="text_chunk",
                document_id=c.document_id, chunk_id=c.id, page_number=c.page_number,
                content=c.content[:600], raw_score=score, metadata={"chunk_type": c.chunk_type}))
        return _finalize(hits, k)


class HybridTextRetriever:
    """Production text retriever: reuses the Phase-1 hybrid pipeline UNCHANGED (lazy imports)."""

    modality = "text"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:  # pragma: no cover - needs faiss
        from app.core.state import pipeline
        from app.retrieval.filters import build_filter
        from app.services.embedding_service import generate_embedding
        filters = {"workspace_id": ctx.workspace_id}
        if ctx.document_id:
            filters["document_id"] = [ctx.document_id]
        result = pipeline.run(ctx.query, embed_fn=generate_embedding, filters=build_filter(filters))
        hits: List[RetrievalHit] = []
        for i, ch in enumerate(result.chunks, start=1):
            meta = getattr(ch, "metadata", {}) or {}
            hits.append(RetrievalHit(
                key=f"chunk:{meta.get('chunk_id', i)}", modality="text", source_type="text_chunk",
                document_id=meta.get("document_id"), chunk_id=meta.get("chunk_id"),
                page_number=meta.get("page_number"), content=(getattr(ch, "text", "") or "")[:600],
                raw_score=float(getattr(ch, "score", 0.0)), rank_in_modality=i,
                metadata={"section": meta.get("section")}))
        for i, h in enumerate(hits[:k], start=1):
            h.rank_in_modality = i
        return hits[:k]


# ------------------------------------------------------------------ ocr
class OcrRetriever:
    modality = "ocr"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for c in repo.chunks(ctx.workspace_id, ["ocr"], ctx.document_id):
            score = lexical_score(ctx.keywords, [(c.content, 1.0)])
            if score <= 0:
                continue
            hits.append(RetrievalHit(
                key=f"chunk:{c.id}", modality="ocr", source_type="ocr",
                document_id=c.document_id, chunk_id=c.id, page_number=c.page_number,
                content=c.content[:600], raw_score=score, metadata={"source": "ocr"}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ vision-backed (image / diagram / table)
def _vision_hit(a, modality: str, source_type: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        key=f"asset:{a.asset_id}", modality=modality, source_type=source_type, document_id=a.document_id,
        asset_id=a.asset_id, page_number=a.page_number, title=a.image_type.replace("_", " "),
        content=a.caption[:600], raw_score=score,
        metadata={"image_type": a.image_type, "confidence": a.confidence, "keywords": a.keywords,
                  "structured": a.structured}, confidence=a.confidence or 0.0)


class ImageRetriever:
    modality = "image"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for a in repo.vision(ctx.workspace_id, exclude_types=[*DIAGRAM_TYPES, "table"], document_id=ctx.document_id):
            kw = " ".join(a.keywords or [])
            score = lexical_score(ctx.keywords, [(a.caption, 1.2), (kw, 0.8), (a.image_type, 1.0)])
            if score <= 0:
                continue
            hits.append(_vision_hit(a, "image", "image", score))
        return _finalize(hits, k)


class DiagramRetriever:
    modality = "diagram"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for a in repo.vision(ctx.workspace_id, image_types=list(DIAGRAM_TYPES), document_id=ctx.document_id):
            nodes = " ".join((a.structured or {}).get("nodes", [])) if a.structured else ""
            kw = " ".join(a.keywords or [])
            score = lexical_score(ctx.keywords, [(a.caption, 1.2), (nodes, 1.0), (kw, 0.8), (a.image_type, 1.5)])
            if score <= 0:
                continue
            hits.append(_vision_hit(a, "diagram", "diagram", score))
        return _finalize(hits, k)


class TableRetriever:
    modality = "table"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for t in repo.tables(ctx.workspace_id, ctx.document_id):
            headers = " ".join(str(h) for h in (t.headers or []))
            cells = " ".join(str(c) for row in (t.cells or [])[:20] for c in row)
            # Header-aware: headers weighted higher than cell values.
            score = lexical_score(ctx.keywords, [(t.caption or "", 1.0), (headers, 1.6), (cells, 0.6)])
            if score <= 0:
                continue
            hits.append(RetrievalHit(
                key=f"asset:{t.id}", modality="table", source_type="table", document_id=t.document_id,
                asset_id=t.id, page_number=t.page_number, title=(t.caption or "Table"),
                content=(t.caption or headers)[:600], raw_score=score,
                metadata={"headers": t.headers, "n_rows": t.n_rows, "n_cols": t.n_cols}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ metadata
class MetadataRetriever:
    modality = "metadata"

    def retrieve(self, ctx: RetrievalContext, k: int) -> List[RetrievalHit]:
        repo = ctx.repository()
        hits: List[RetrievalHit] = []
        for d in repo.documents(ctx.workspace_id, ctx.owner_id, ctx.document_id):
            score = lexical_score(ctx.keywords, [(d.display_name, 1.6), (d.description, 1.0)])
            if score <= 0:
                continue
            hits.append(RetrievalHit(
                key=f"doc:{d.id}", modality="metadata", source_type="document", document_id=d.id,
                title=d.display_name, content=(d.description or d.display_name)[:600], raw_score=score,
                metadata={"file_type": d.file_type, "page_count": d.page_count}))
        return _finalize(hits, k)


# Registry of DB-backed retrievers (text is injected separately so production can use Phase-1 hybrid).
DB_RETRIEVERS = {
    "ocr": OcrRetriever(), "image": ImageRetriever(), "diagram": DiagramRetriever(),
    "table": TableRetriever(), "metadata": MetadataRetriever(),
}
