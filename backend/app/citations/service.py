"""Citation-intelligence business logic — sync orchestration + panel/explorer/explain/search/stats.

The index is kept fresh transparently: every read first calls `ensure_synced`, which compares the
live source-citation count to the indexed reference count and rebuilds only when they differ (a
cheap 5-query check when in sync). Callers never think about indexing.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.citations.errors import CitationNotFound
from app.citations.explain import explain as compose_explanation
from app.citations.indexer import CitationIndexer
from app.citations.models import Citation
from app.citations.repository import CitationRepository
from app.citations.schemas import CitationSortField, ReferenceType, SortOrder


class CitationService:
    def __init__(self, repo: CitationRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ sync
    def ensure_synced(self, workspace_id: str, owner_id: str, *, force: bool = False) -> int:
        """Rebuild the workspace index iff the source citation count changed (or forced)."""
        indexer = CitationIndexer(self.db)
        if force:
            return indexer.rebuild(workspace_id, owner_id)
        src = indexer.source_reference_count(workspace_id)
        idx = indexer.indexed_reference_count(workspace_id)
        if src != idx:
            return indexer.rebuild(workspace_id, owner_id)
        return -1  # already fresh

    def reindex(self, workspace_id: str, owner_id: str) -> int:
        return CitationIndexer(self.db).rebuild(workspace_id, owner_id)

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, citation_id: str, workspace_id: str) -> Citation:
        c = self.repo.get(citation_id, workspace_id)
        if c is None:
            raise CitationNotFound(citation_id)
        return c

    # ------------------------------------------------------------------ reads
    def search(self, workspace_id: str, owner_id: str, **kw) -> Tuple[List[Citation], int]:
        self.ensure_synced(workspace_id, owner_id)
        kw["page"] = max(1, kw.get("page", 1))
        kw["page_size"] = min(max(1, kw.get("page_size", 20)), 100)
        return self.repo.search(workspace_id, **kw)

    def detail(self, citation_id: str, workspace_id: str, owner_id: str):
        self.ensure_synced(workspace_id, owner_id)
        c = self._get_or_404(citation_id, workspace_id)
        refs = self.repo.references_for(c.id)
        by_type = self.repo.reference_type_counts(c.id)
        cit_count, ref_count = self.repo.document_context(workspace_id, c.document_id)
        return c, refs, by_type, {"document_id": c.document_id, "citation_count": cit_count, "reference_count": ref_count}

    def by_chunk(self, workspace_id: str, owner_id: str, document_id: Optional[str], chunk_id: Optional[str]):
        """Resolve a citation from a chunk/document (used when opening the panel from an artifact)."""
        self.ensure_synced(workspace_id, owner_id)
        c = self.repo.get_by_chunk(workspace_id, document_id, chunk_id)
        if c is None:
            raise CitationNotFound(chunk_id or document_id or "unknown")
        return self.detail(c.id, workspace_id, owner_id)

    def related(self, citation_id: str, workspace_id: str, owner_id: str):
        """Knowledge Explorer payload: chunk↔chunk neighbours + same-document + reference-type mix."""
        self.ensure_synced(workspace_id, owner_id)
        c = self._get_or_404(citation_id, workspace_id)
        edges = self.repo.knowledge_for(c.id)
        related = []
        for k, neighbour in edges:
            related.append({
                "citation_id": k.related_citation_id,
                "chunk_id": k.related_chunk_id,
                "document_id": k.related_document_id,
                "relationship": k.relationship,
                "strength": k.strength,
                "page_number": neighbour.page_number if neighbour else None,
                "citation_text": (neighbour.citation_text[:240] if neighbour else ""),
            })
        by_type = self.repo.reference_type_counts(c.id)
        same_doc = self.repo.same_document_citations(workspace_id, c.document_id, exclude_id=c.id) if c.document_id else []
        return c, related, by_type, same_doc

    def explain(self, citation_id: str, workspace_id: str, owner_id: str) -> dict:
        self.ensure_synced(workspace_id, owner_id)
        c = self._get_or_404(citation_id, workspace_id)
        by_type = self.repo.reference_type_counts(c.id)
        return compose_explanation(c, reference_counts=by_type)

    def stats(self, workspace_id: str, owner_id: str) -> Dict:
        self.ensure_synced(workspace_id, owner_id)
        return self.repo.stats(workspace_id)
