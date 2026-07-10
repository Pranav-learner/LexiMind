"""The summary engine — the ONLY bridge from a summary request to the AI pipeline.

Like the chat engine, the summaries module implements NO retrieval/context logic. This engine
plans a set of sections for the requested summary type, and for EACH section runs the existing
pipeline (retrieval → context → LLM) so every section is grounded and carries preserved citations.

It is injected (`get_summary_runner` builds the production one) and imports the heavy singletons
LAZILY, so `app.summaries.*` imports with no faiss/torch and tests substitute a fake engine.

Hierarchical summarization: for `detailed`/`chapterwise`, sections are derived from the
document's own headings (intermediate, per-section summaries), then a final synthesis section
aggregates them — the "chunk groups → intermediate summaries → final summary" strategy.

Event protocol (a generator of dicts):
    {"type": "plan",    "total": int, "model": str, "language": str}
    {"type": "section", "heading": str, "order": int, "content": str, "citations": [ {...} ]}
    {"type": "final",   "token_usage": int}
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Protocol, Tuple

# Fixed section plans for the light-weight summary types.
_FIXED_PLANS: Dict[str, List[Tuple[str, str]]] = {
    "quick": [("Executive Overview", "Give a concise executive overview of the material.")],
    "bullet": [("Key Points", "What are the most important points, facts, and takeaways?")],
    "standard": [
        ("Overview", "Give a high-level overview of the material."),
        ("Key Concepts", "What are the key concepts, definitions, and ideas?"),
        ("Conclusions", "What are the main conclusions, results, or takeaways?"),
    ],
}

# For detailed/chapterwise without derivable headings, fall back to these themes.
_THEME_PLAN: List[Tuple[str, str]] = [
    ("Introduction & Scope", "What is the subject, motivation, and scope?"),
    ("Core Concepts", "Explain the core concepts and definitions in depth."),
    ("Methods & Details", "What methods, mechanisms, or details are described?"),
    ("Findings & Results", "What are the findings, results, or key arguments?"),
    ("Conclusions", "What are the conclusions and their implications?"),
]

_MAX_DERIVED_SECTIONS = 12


class SummaryEngine(Protocol):
    def generate(self, summary, db: Any) -> Iterator[Dict[str, Any]]:
        ...


class PipelineSummaryEngine:
    """Production engine: reuses retrieval → context → LLM per section, then a final synthesis."""

    def generate(self, summary, db: Any) -> Iterator[Dict[str, Any]]:
        # --- lazy heavy imports (keep app.summaries.* faiss-free at import time) ---
        from app.context.tokenizer import heuristic_token_count
        from app.core.config import settings
        from app.core.state import context_builder, pipeline
        from app.documents import indexing
        from app.documents.repository import DocumentRepository
        from app.retrieval.filters import build_filter
        from app.services.answer_service import build_summary_prompt, complete, structured_citations
        from app.services.embedding_service import generate_embedding

        vector_ids, vector_store = self._resolve_scope(summary, db, DocumentRepository)
        plan = self._plan_sections(summary, vector_ids, vector_store, indexing)

        yield {"type": "plan", "total": len(plan) + (1 if self._needs_synthesis(summary) else 0),
               "model": settings.llm_model, "language": summary.language}

        # Base retrieval filter: workspace isolation + archived/deleted exclusion + doc scope.
        base_filter: Dict[str, Any] = {"workspace_id": summary.workspace_id}
        if vector_ids:
            base_filter["document_id"] = vector_ids
        hidden = DocumentRepository(db).list_excluded_vector_ids(summary.workspace_id)
        if hidden:
            base_filter["exclude_document_id"] = hidden

        token_usage = 0
        section_texts: List[str] = []
        order = 0
        for heading, query in plan:
            order += 1
            result = pipeline.run(query, embed_fn=generate_embedding, filters=build_filter(base_filter))
            ctx = context_builder.build(query, result.chunks, query_keywords=result.analysis.keywords)
            content = complete(build_summary_prompt(summary.summary_type, heading, ctx.context))
            citations = structured_citations(ctx.evidence)
            token_usage += heuristic_token_count(content)
            section_texts.append(f"## {heading}\n{content}")
            yield {"type": "section", "heading": heading, "order": order,
                   "content": content, "citations": citations}

        # Hierarchical final aggregation (intermediate section summaries → one synthesis).
        if self._needs_synthesis(summary) and section_texts:
            order += 1
            synth_ctx = "\n\n".join(section_texts)
            content = complete(build_summary_prompt("quick", "Overall Synthesis", synth_ctx))
            token_usage += heuristic_token_count(content)
            yield {"type": "section", "heading": "Overall Synthesis", "order": order,
                   "content": content, "citations": []}

        yield {"type": "final", "token_usage": token_usage}

    # ------------------------------------------------------------------ helpers
    def _resolve_scope(self, summary, db, DocumentRepository):
        """Resolve the summary's scope to the vector document ids retrieval should filter on."""
        from app.core.state import vector_store

        repo = DocumentRepository(db)
        vids: List[str] = []
        if summary.scope == "document" and summary.document_id:
            doc = repo.get(summary.document_id, summary.owner_id)
            if doc:
                vids = [doc.vector_document_id]
        elif summary.scope == "multi" and summary.document_ids:
            for did in summary.document_ids:
                doc = repo.get(did, summary.owner_id)
                if doc:
                    vids.append(doc.vector_document_id)
        # scope == "workspace" → no doc filter (whole workspace)
        return vids, vector_store

    def _plan_sections(self, summary, vector_ids, vector_store, indexing) -> List[Tuple[str, str]]:
        t = summary.summary_type
        if t in _FIXED_PLANS:
            return list(_FIXED_PLANS[t])
        # detailed / chapterwise: derive from a single document's real headings when possible.
        if t in ("detailed", "chapterwise") and summary.scope == "document" and len(vector_ids) == 1:
            headings = self._derive_headings(vector_store, vector_ids[0], summary.workspace_id, indexing)
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

    def _needs_synthesis(self, summary) -> bool:
        return summary.summary_type in ("detailed", "chapterwise")
