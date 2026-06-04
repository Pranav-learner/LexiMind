from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.state import context_builder, pipeline
from app.retrieval.filters import build_filter
from app.services.answer_service import format_citations, generate_answer
from app.services.embedding_service import generate_embedding

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str
    # Optional metadata filters: {document_id|workspace|source|topic: str | [str]}
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = None


@router.post("")
def query_knowledge(req: QueryRequest):
    # Phase 1 — retrieval: query analysis -> dense + BM25 -> RRF -> rerank.
    result = pipeline.run(
        req.question,
        embed_fn=generate_embedding,
        filters=build_filter(req.filters),
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
