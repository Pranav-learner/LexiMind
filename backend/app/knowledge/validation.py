"""Knowledge-graph vocabularies + pure validators (transport-agnostic).

The fixed entity/relationship type sets are the schema the extractor, resolver and validator agree on.
User-defined entity types (Step 3 future) can extend `ENTITY_TYPES` without code changes elsewhere.
"""

from __future__ import annotations

import re

ENTITY_TYPES = (
    "person", "organization", "location", "technology", "language", "framework", "algorithm",
    "data_structure", "library", "paper", "book", "product", "concept", "custom",
)

RELATIONSHIP_TYPES = (
    "uses", "implements", "depends_on", "part_of", "references", "explains", "defines", "extends",
    "calls", "created_by", "inspired_by", "compared_with", "prerequisite", "successor", "related_to",
    "supports", "is_a",
)

# relationships for which a self-loop (source == target) is invalid
NO_SELF_LOOP = frozenset({"depends_on", "part_of", "extends", "prerequisite", "successor", "is_a", "calls"})

_NORM_STRIP = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    """Canonical dedup key: lowercase, punctuation/space-insensitive (Node.js == NodeJS == node js)."""
    return _NORM_STRIP.sub("", (name or "").lower())


def is_valid_entity_type(t: str) -> bool:
    return t in ENTITY_TYPES


def is_valid_relationship_type(t: str) -> bool:
    return t in RELATIONSHIP_TYPES


def valid_entity_name(name: str) -> bool:
    n = (name or "").strip()
    return 2 <= len(n) <= 300 and bool(normalize_name(n))
