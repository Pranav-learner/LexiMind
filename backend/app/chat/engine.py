"""The chat engine — the single bridge from a chat turn to the EXISTING AI pipeline.

The chat module implements NO retrieval or context logic of its own. This engine orchestrates
the already-built services (Phase-1 `RetrievalPipeline`, Phase-2 `ContextBuilderService`, the
`answer_service` LLM call) and yields a stream of events the chat service persists and forwards.

It is injected into the API as a dependency (`get_chat_engine`) and imports the heavy singletons
(`app.core.state`, embeddings, FAISS) LAZILY inside `generate()`, so `app.chat.*` imports with no
faiss/torch and tests can substitute a fast fake engine.

Event protocol (a generator of dicts):
    {"type": "token", "text": "..."}     # 0+ progressive tokens
    {"type": "final", "answer": str, "citations": [ {...} ],
     "retrieval_ms": int, "context_size": int, "token_usage": int, "latency_ms": int}
Exactly one "final" event ends the stream.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional, Protocol


class ChatEngine(Protocol):
    def generate(
        self,
        question: str,
        workspace_id: str,
        history: List[Dict[str, Any]],
        *,
        db: Any = None,
        top_k: Optional[int] = None,
        document_scope: Optional[List[str]] = None,
    ) -> Iterator[Dict[str, Any]]:
        ...


class PipelineChatEngine:
    """Production engine: reuses retrieval → context → LLM, streaming the LLM tokens."""

    def generate(
        self,
        question: str,
        workspace_id: str,
        history: List[Dict[str, Any]],
        *,
        db: Any = None,
        top_k: Optional[int] = None,
        document_scope: Optional[List[str]] = None,
    ) -> Iterator[Dict[str, Any]]:
        # --- lazy heavy imports (keep app.chat.* faiss-free at import time) ---
        from app.context.tokenizer import heuristic_token_count
        from app.core.state import context_builder, pipeline
        from app.documents.repository import DocumentRepository
        from app.retrieval.filters import build_filter
        from app.services.answer_service import (
            build_chat_prompt,
            stream_answer,
            structured_citations,
        )
        from app.services.embedding_service import generate_embedding

        started = time.perf_counter()

        # Workspace isolation + archived/deleted exclusion (same rules as /query).
        filters: Dict[str, Any] = {"workspace_id": workspace_id}
        if document_scope:
            filters["document_id"] = document_scope  # document-scoped conversation
        if db is not None:
            hidden = DocumentRepository(db).list_excluded_vector_ids(workspace_id)
            if hidden:
                filters["exclude_document_id"] = hidden

        r0 = time.perf_counter()
        result = pipeline.run(
            question,
            embed_fn=generate_embedding,
            filters=build_filter(filters),
            final_top_k=top_k,
        )
        retrieval_ms = int((time.perf_counter() - r0) * 1000)

        ctx = context_builder.build(
            question, result.chunks, query_keywords=result.analysis.keywords
        )

        prompt = build_chat_prompt(question, ctx.context, history)

        answer_parts: List[str] = []
        for token in stream_answer(prompt):
            answer_parts.append(token)
            yield {"type": "token", "text": token}
        answer = "".join(answer_parts).strip()

        citations = structured_citations(ctx.evidence)
        yield {
            "type": "final",
            "answer": answer,
            "citations": citations,
            "retrieval_ms": retrieval_ms,
            "context_size": heuristic_token_count(ctx.context or ""),
            "token_usage": heuristic_token_count(answer),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
