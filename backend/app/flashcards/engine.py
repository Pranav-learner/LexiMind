"""The flashcard engine — the ONLY bridge from a generation request to the AI pipeline.

Like the notes/summaries/chat engines, this module implements NO retrieval/context logic. It plans
a set of retrieval queries for the deck's scope, and for EACH query runs the existing pipeline
(retrieval → context → LLM) and parses the LLM's structured output into grounded cards that carry
the citations Phase 2 preserved.

Injected (`get_flashcards_runner` builds the production one) and imports the heavy singletons
LAZILY, so `app.flashcards.*` imports with no faiss/torch and tests substitute a fake engine.

Event protocol for `generate` (a generator of dicts):
    {"type": "plan",  "total": int (target cards), "model": str}
    {"type": "card",  "front", "back", "hint", "card_type", "citations": [ {...} ]}
    {"type": "final", "token_usage": int}
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Protocol

# Retrieval queries used to elicit study-worthy content. For a document scope we also mine the
# document's real headings; these generic prompts are the fallback / workspace-scope plan.
_TOPIC_QUERIES: List[str] = [
    "key concepts and definitions",
    "important facts and details",
    "core mechanisms and how things work",
    "main conclusions and results",
    "terminology worth memorizing",
]
_MAX_QUERIES = 8


class FlashcardEngine(Protocol):
    def generate(self, deck, db: Any, *, count: int) -> Iterator[Dict[str, Any]]:
        ...


class PipelineFlashcardEngine:
    """Production engine: reuses retrieval → context → LLM per query, parses cards, attaches citations."""

    def generate(self, deck, db: Any, *, count: int) -> Iterator[Dict[str, Any]]:
        from app.context.tokenizer import heuristic_token_count
        from app.core.config import settings
        from app.core.state import context_builder, pipeline
        from app.documents import indexing
        from app.documents.repository import DocumentRepository
        from app.retrieval.filters import build_filter
        from app.services.answer_service import build_flashcard_prompt, complete, parse_flashcards, structured_citations
        from app.services.embedding_service import generate_embedding

        vector_ids = self._resolve_scope(deck, db, DocumentRepository)
        queries = self._plan_queries(deck, vector_ids, indexing)

        yield {"type": "plan", "total": count, "model": settings.llm_model}

        base_filter: Dict[str, Any] = {"workspace_id": deck.workspace_id}
        if vector_ids:
            base_filter["document_id"] = vector_ids
        hidden = DocumentRepository(db).list_excluded_vector_ids(deck.workspace_id)
        if hidden:
            base_filter["exclude_document_id"] = hidden

        pref = deck.card_type_pref or "mixed"
        # Distribute the target card count across the planned queries.
        per_query = max(2, -(-count // max(1, len(queries))))  # ceil
        emitted = 0
        token_usage = 0
        seen_fronts: set[str] = set()

        for query in queries:
            if emitted >= count:
                break
            result = pipeline.run(query, embed_fn=generate_embedding, filters=build_filter(base_filter))
            if not result.chunks:
                continue
            ctx = context_builder.build(query, result.chunks, query_keywords=result.analysis.keywords)
            raw = complete(build_flashcard_prompt(pref, per_query, ctx.context))
            token_usage += heuristic_token_count(raw)
            citations = structured_citations(ctx.evidence)
            for card in parse_flashcards(raw, default_type="basic" if pref == "mixed" else pref):
                key = card["front"].strip().lower()[:120]
                if key in seen_fronts:
                    continue  # dedup near-identical fronts across queries
                seen_fronts.add(key)
                yield {"type": "card", **card, "citations": citations}
                emitted += 1
                if emitted >= count:
                    break

        yield {"type": "final", "token_usage": token_usage}

    # ------------------------------------------------------------------ helpers
    def _resolve_scope(self, deck, db, DocumentRepository) -> List[str]:
        repo = DocumentRepository(db)
        vids: List[str] = []
        if deck.scope == "document" and deck.document_id:
            doc = repo.get(deck.document_id, deck.owner_id)
            if doc:
                vids = [doc.vector_document_id]
        elif deck.scope == "multi" and deck.document_ids:
            for did in deck.document_ids:
                doc = repo.get(did, deck.owner_id)
                if doc:
                    vids.append(doc.vector_document_id)
        return vids

    def _plan_queries(self, deck, vector_ids, indexing) -> List[str]:
        # A seed subject (e.g. a PDF selection) focuses generation on that topic.
        if deck.subject and deck.subject.strip():
            base = [deck.subject.strip()]
            return base + _TOPIC_QUERIES[:3]
        # Single document → mine real headings for topical coverage.
        if deck.scope == "document" and len(vector_ids) == 1:
            from app.core.state import vector_store
            headings = self._derive_headings(vector_store, vector_ids[0], deck.workspace_id, indexing)
            if headings:
                return headings[:_MAX_QUERIES]
        return list(_TOPIC_QUERIES)

    def _derive_headings(self, vector_store, vector_document_id, workspace_id, indexing) -> List[str]:
        records = indexing.list_document_chunks(vector_store, vector_document_id, workspace_id)
        seen, headings = set(), []
        for m in records:
            h = (m.get("section") or m.get("section_heading") or "").strip()
            if h and h.lower() not in seen:
                seen.add(h.lower())
                headings.append(h)
        return headings
