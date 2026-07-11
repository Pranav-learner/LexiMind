"""The notes engine — the ONLY bridge from a note request to the AI pipeline.

Like the summaries/chat engines, the notes module implements NO retrieval/context logic. This
engine plans a set of sections for the requested note template, and for EACH section runs the
existing pipeline (retrieval → context → LLM) so every section is grounded and carries preserved
citations. It also serves synchronous AI-assisted edits on a text selection.

Injected (`get_notes_runner`/`get_notes_engine` build the production one) and imports the heavy
singletons LAZILY, so `app.notes.*` imports with no faiss/torch and tests substitute a fake engine.

Event protocol for `generate` (a generator of dicts):
    {"type": "plan",    "total": int, "model": str}
    {"type": "section", "heading": str, "order": int, "content": str, "citations": [ {...} ]}
    {"type": "final",   "token_usage": int}
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Protocol, Tuple

# Fixed section plans per note template. (heading, retrieval query) tuples. Architecture supports
# future CUSTOM templates by adding an entry here + a style in answer_service._NOTE_STYLE.
_FIXED_PLANS: Dict[str, List[Tuple[str, str]]] = {
    "quick": [("Key Notes", "What are the most important facts and takeaways?")],
    "study": [
        ("Overview", "Give a high-level overview of the material."),
        ("Key Concepts", "What are the key concepts, definitions, and ideas?"),
        ("Important Details", "What important details, mechanisms, or facts matter most?"),
        ("Takeaways", "What are the main conclusions and takeaways?"),
    ],
    "concept": [
        ("Core Concept", "Explain the single most important concept in depth."),
        ("How It Works", "How does it work? What are the mechanisms and relationships?"),
        ("Examples", "What concrete examples illustrate this concept?"),
    ],
    "revision": [
        ("Must-Know Facts", "What are the most test-worthy, must-know facts?"),
        ("Definitions", "What key terms and definitions should be memorized?"),
        ("Quick Review", "Summarize everything for a fast last-minute review."),
    ],
}

# For detailed/chapterwise, derive sections from a single document's real headings when possible.
_THEME_PLAN: List[Tuple[str, str]] = [
    ("Introduction & Scope", "What is the subject, motivation, and scope?"),
    ("Core Concepts", "Explain the core concepts and definitions in depth."),
    ("Methods & Details", "What methods, mechanisms, or details are described?"),
    ("Findings & Results", "What are the findings, results, or key arguments?"),
    ("Conclusions", "What are the conclusions and their implications?"),
]

_MAX_DERIVED_SECTIONS = 12


class NotesEngine(Protocol):
    def generate(self, note, db: Any) -> Iterator[Dict[str, Any]]:
        ...

    def assist(self, note, db: Any, *, operation: str, selection: str,
               instruction: str | None, ground: bool) -> str:
        ...


class PipelineNotesEngine:
    """Production engine: reuses retrieval → context → LLM per section, plus assisted edits."""

    # ------------------------------------------------------------------ generation
    def generate(self, note, db: Any) -> Iterator[Dict[str, Any]]:
        from app.context.tokenizer import heuristic_token_count
        from app.core.config import settings
        from app.core.state import context_builder, pipeline
        from app.documents import indexing
        from app.documents.repository import DocumentRepository
        from app.retrieval.filters import build_filter
        from app.services.answer_service import build_notes_prompt, complete, structured_citations
        from app.services.embedding_service import generate_embedding

        vector_ids = self._resolve_scope(note, db, DocumentRepository)
        plan = self._plan_sections(note, vector_ids, indexing)

        yield {"type": "plan", "total": len(plan), "model": settings.llm_model}

        base_filter: Dict[str, Any] = {"workspace_id": note.workspace_id}
        if vector_ids:
            base_filter["document_id"] = vector_ids
        hidden = DocumentRepository(db).list_excluded_vector_ids(note.workspace_id)
        if hidden:
            base_filter["exclude_document_id"] = hidden

        token_usage = 0
        order = 0
        note_type = note.note_type or "study"
        for heading, query in plan:
            order += 1
            result = pipeline.run(query, embed_fn=generate_embedding, filters=build_filter(base_filter))
            ctx = context_builder.build(query, result.chunks, query_keywords=result.analysis.keywords)
            content = complete(build_notes_prompt(note_type, heading, ctx.context))
            citations = structured_citations(ctx.evidence)
            token_usage += heuristic_token_count(content)
            yield {"type": "section", "heading": heading, "order": order,
                   "content": content, "citations": citations}

        yield {"type": "final", "token_usage": token_usage}

    # ------------------------------------------------------------------ assisted editing
    def assist(self, note, db: Any, *, operation: str, selection: str,
               instruction: str | None, ground: bool) -> str:
        from app.core.state import context_builder, pipeline
        from app.documents.repository import DocumentRepository
        from app.retrieval.filters import build_filter
        from app.services.answer_service import (
            NOTE_ASSIST_GROUNDED,
            build_note_assist_prompt,
            complete,
        )
        from app.services.embedding_service import generate_embedding

        context = None
        if ground and operation in NOTE_ASSIST_GROUNDED and selection.strip():
            base_filter: Dict[str, Any] = {"workspace_id": note.workspace_id}
            vids = self._resolve_scope(note, db, DocumentRepository)
            if vids:
                base_filter["document_id"] = vids
            result = pipeline.run(selection[:500], embed_fn=generate_embedding,
                                  filters=build_filter(base_filter))
            ctx = context_builder.build(selection[:500], result.chunks,
                                        query_keywords=result.analysis.keywords)
            context = ctx.context
        return complete(build_note_assist_prompt(operation, selection, instruction=instruction, context=context))

    # ------------------------------------------------------------------ helpers
    def _resolve_scope(self, note, db, DocumentRepository) -> List[str]:
        repo = DocumentRepository(db)
        vids: List[str] = []
        if note.scope == "document" and note.document_id:
            doc = repo.get(note.document_id, note.owner_id)
            if doc:
                vids = [doc.vector_document_id]
        elif note.scope == "multi" and note.document_ids:
            for did in note.document_ids:
                doc = repo.get(did, note.owner_id)
                if doc:
                    vids.append(doc.vector_document_id)
        # scope == "workspace" → no doc filter (whole workspace)
        return vids

    def _plan_sections(self, note, vector_ids, indexing) -> List[Tuple[str, str]]:
        from app.core.state import vector_store

        t = note.note_type or "study"
        if t in _FIXED_PLANS:
            return list(_FIXED_PLANS[t])
        # detailed / chapterwise: derive from a single document's real headings when possible.
        if t in ("detailed", "chapterwise") and note.scope == "document" and len(vector_ids) == 1:
            headings = self._derive_headings(vector_store, vector_ids[0], note.workspace_id, indexing)
            if headings:
                return [(h, f"Summarize the section: {h}") for h in headings[:_MAX_DERIVED_SECTIONS]]
        return list(_THEME_PLAN)

    def _derive_headings(self, vector_store, vector_document_id, workspace_id, indexing) -> List[str]:
        records = indexing.list_document_chunks(vector_store, vector_document_id, workspace_id)
        seen, headings = set(), []
        for m in records:
            h = (m.get("section") or m.get("section_heading") or "").strip()
            if h and h.lower() not in seen:
                seen.add(h.lower())
                headings.append(h)
        return headings
