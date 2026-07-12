"""Entity-aware query understanding (Step 3) — resolve a query into canonical GRAPH entities.

REUSES Module-1 extraction (the SAME `EntityExtractor` + gazetteer) to pull candidate entities from the
query, then matches them against the workspace graph (by normalized name / alias) so only entities that
actually EXIST as nodes become seeds. Falls back to a keyword entity search when extraction finds nothing
(e.g. "explain virtual memory" → the `Virtual Memory` node). No new NER pipeline is created.
"""

from __future__ import annotations

from typing import List

from app.knowledge.extraction import EntityExtractor
from app.knowledge.models import GraphEntity
from app.knowledge.repository import GraphRepository
from app.knowledge.validation import normalize_name


class QueryEntityRecognizer:
    name = "graph-recognizer-v1"

    def __init__(self, *, extractor: EntityExtractor = None):
        self.extractor = extractor or EntityExtractor()

    def recognize(self, query: str, workspace_id: str, owner_id: str, *,
                  repo: GraphRepository = None, db=None) -> List[GraphEntity]:
        repo = repo or GraphRepository(db)
        # index the workspace graph by normalized name + alias for O(1) resolution
        entities = repo.workspace_entities(workspace_id, owner_id)
        index = {}
        for e in entities:
            index.setdefault(e.normalized_name, e)
            for a in (e.aliases or []):
                index.setdefault(normalize_name(a), e)

        seeds: List[GraphEntity] = []
        seen = set()
        for ex in self.extractor.extract(query, {"source_type": "query"}):
            match = index.get(normalize_name(ex.canonical_name))
            if match is None:
                for a in ex.aliases:
                    match = index.get(normalize_name(a))
                    if match:
                        break
            if match is not None and match.id not in seen:
                seen.add(match.id); seeds.append(match)

        if not seeds:
            # keyword fallback: match query tokens against entity names directly
            for e in repo.search_entities(workspace_id, owner_id, query=query, limit=5):
                if e.id not in seen:
                    seen.add(e.id); seeds.append(e)
        return seeds
