from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.state import context_builder, pipeline
from app.db.base import get_db
from app.documents.repository import DocumentRepository
from app.retrieval.filters import build_filter
from app.services.answer_service import format_citations, generate_answer
from app.services.embedding_service import generate_embedding

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str
    # Phase 3: scope the query to one workspace. Optional for backward compatibility — a
    # request with no workspace_id searches the whole index exactly as before.
    workspace_id: Optional[str] = None
    # Optional metadata filters: {document_id|workspace_id|source|topic: str | [str]}
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = None


@router.post("")
def query_knowledge(req: QueryRequest, db: Session = Depends(get_db)):
    # Merge the top-level workspace_id into the filter dict (explicit filters win if both
    # set the field). This keeps the workspace boundary a first-class, easy-to-use param.
    filters = dict(req.filters or {})
    if req.workspace_id and "workspace_id" not in filters:
        filters["workspace_id"] = req.workspace_id

    # Phase-3 Module-2: keep ARCHIVED / soft-deleted documents out of normal retrieval by
    # excluding their vector ids. A cheap, indexed DB lookup; no mutation of the vector store.
    if req.workspace_id and "exclude_document_id" not in filters:
        hidden = DocumentRepository(db).list_excluded_vector_ids(req.workspace_id)
        if hidden:
            filters["exclude_document_id"] = hidden

    # Phase 1 — retrieval: query analysis -> dense + BM25 -> RRF -> rerank.
    result = pipeline.run(
        req.question,
        embed_fn=generate_embedding,
        filters=build_filter(filters),
        final_top_k=req.top_k,
    )

    # Phase 2 — context engineering: dedup -> rank -> budget -> compress -> assemble.
    ctx = context_builder.build(
        req.question,
        result.chunks,
        query_keywords=result.analysis.keywords,
    )

    # The LLM now consumes the single, engineered context (no more duplicate builder).
    answer = generate_answer(req.question, ctx.context)
    sources = format_citations(ctx.citations)

    return {
        "question": req.question,
        "answer": answer,
        "sources": sources,
        "analysis": {
            "query_type": result.analysis.query_type,
            "intent": result.analysis.intent,
            "keywords": result.analysis.keywords,
        },
        "retrieval": {
            "num_candidates": len(result.chunks),
            "timings_ms": {k: round(v, 2) for k, v in result.timings_ms.items()},
        },
        "context": ctx.metrics,
    }
