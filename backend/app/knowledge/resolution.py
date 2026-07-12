"""Entity Resolution + Deduplication (Steps 5–6) — one canonical node per real-world concept.

`GraphResolver` builds an in-memory index of the workspace's existing entities (canonical + every alias,
normalized) so an extracted entity is matched to its canonical node by:
- exact normalized match ("Node.js" == "NodeJS" == "node js"),
- alias match ("LLM" → "Large Language Model", "OS" → "Operating System"),
and registered back into the index so later mentions in the SAME build also merge. Cross-document /
cross-modal / cross-build dedup falls out because the index is seeded from the persisted graph.

Embedding-similarity matching (Step 6) is a declared future signal — the resolver exposes the seam
(`match`) so a vector backend can add fuzzy candidates without changing the builder.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.knowledge.extraction import ExtractedEntity
from app.knowledge.models import GraphEntity
from app.knowledge.validation import normalize_name


class GraphResolver:
    def __init__(self, existing: Optional[List[GraphEntity]] = None):
        self._by_key: Dict[str, GraphEntity] = {}
        for e in (existing or []):
            self._register(e)

    def _register(self, entity: GraphEntity) -> None:
        self._by_key.setdefault(normalize_name(entity.canonical_name), entity)
        for a in (entity.aliases or []):
            self._by_key.setdefault(normalize_name(a), entity)

    def register_new(self, entity: GraphEntity) -> None:
        """Add a just-created entity so subsequent extractions in the same build merge into it."""
        self._register(entity)

    def match(self, extracted: ExtractedEntity) -> Optional[GraphEntity]:
        """Return the canonical entity this extraction belongs to, or None if it's new."""
        keys = [normalize_name(extracted.canonical_name)]
        keys += [normalize_name(a) for a in extracted.aliases]
        for k in keys:
            if k and k in self._by_key:
                return self._by_key[k]
        return None

    def is_empty(self) -> bool:
        return not self._by_key
