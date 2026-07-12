"""Deterministic knowledge base (gazetteer) for entity typing + canonical resolution.

A curated dictionary of well-known technical entities → (canonical name, type, aliases). It powers
high-confidence, LLM-free entity typing and canonicalization (Step 5 resolution: "LLM" → "Large
Language Model", "NodeJS" → "Node.js"). It is intentionally small + extensible: a future spaCy/LLM
extractor (the injected engine seam) supplements it; user-defined entries append without code changes.

Also holds the relationship CUE patterns (Step 4) mapping verb phrases → typed relationships.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# (canonical, type, [aliases])
_GAZETTEER: List[Tuple[str, str, List[str]]] = [
    # languages
    ("Python", "language", ["py"]),
    ("JavaScript", "language", ["js", "ecmascript"]),
    ("TypeScript", "language", ["ts"]),
    ("Java", "language", []),
    ("C++", "language", ["cpp"]),
    ("Go", "language", ["golang"]),
    ("Rust", "language", []),
    ("SQL", "language", []),
    # frameworks / libraries
    ("Node.js", "framework", ["nodejs", "node js", "node"]),
    ("React", "framework", ["react.js", "reactjs"]),
    ("FastAPI", "framework", []),
    ("Django", "framework", []),
    ("PyTorch", "library", ["torch"]),
    ("TensorFlow", "library", ["tf"]),
    ("FAISS", "library", ["faiss"]),
    ("SQLAlchemy", "library", []),
    ("spaCy", "library", ["spacy"]),
    # technologies / concepts
    ("Large Language Model", "concept", ["llm", "llms"]),
    ("Retrieval-Augmented Generation", "concept", ["rag"]),
    ("Knowledge Graph", "concept", ["kg", "knowledge graphs"]),
    ("Operating System", "concept", ["os"]),
    ("Machine Learning", "concept", ["ml"]),
    ("Artificial Intelligence", "concept", ["ai"]),
    ("Natural Language Processing", "concept", ["nlp"]),
    ("Application Programming Interface", "concept", ["api", "apis"]),
    ("Mutual Exclusion", "concept", ["mutex", "mutexes"]),
    ("Deadlock", "concept", ["deadlocks"]),
    ("Semaphore", "concept", ["semaphores"]),
    ("Transmission Control Protocol", "concept", ["tcp"]),
    ("Cross-Encoder", "algorithm", ["cross encoder"]),
    ("Reciprocal Rank Fusion", "algorithm", ["rrf"]),
    ("BM25", "algorithm", ["bm-25"]),
    # data structures / algorithms
    ("B-Tree", "data_structure", ["b tree", "btree"]),
    ("Hash Table", "data_structure", ["hashtable", "hash map", "hashmap"]),
    ("Binary Search Tree", "data_structure", ["bst"]),
    ("Graph", "data_structure", []),
    ("Dijkstra's Algorithm", "algorithm", ["dijkstra"]),
    # organizations / products
    ("OpenAI", "organization", []),
    ("Google", "organization", []),
    ("Anthropic", "organization", []),
    ("GPT", "product", ["openai gpt", "gpt-4", "gpt4", "chatgpt"]),
    ("Neo4j", "product", ["neo4j"]),
    ("PostgreSQL", "product", ["postgres", "postgresql"]),
]


def _build() -> Tuple[Dict[str, Tuple[str, str]], Dict[str, List[str]]]:
    """alias/canonical(normalized) -> (canonical, type); canonical -> alias list."""
    from app.knowledge.validation import normalize_name
    lookup: Dict[str, Tuple[str, str]] = {}
    alias_map: Dict[str, List[str]] = {}
    for canonical, etype, aliases in _GAZETTEER:
        alias_map[canonical] = aliases
        lookup[normalize_name(canonical)] = (canonical, etype)
        for a in aliases:
            lookup[normalize_name(a)] = (canonical, etype)
    return lookup, alias_map


LOOKUP, ALIASES = _build()


def resolve(surface: str) -> Tuple[str, str] | None:
    """Return (canonical_name, entity_type) if `surface` is a known entity/alias, else None."""
    from app.knowledge.validation import normalize_name
    return LOOKUP.get(normalize_name(surface))


def surface_forms() -> List[str]:
    """All known surface strings (canonicals + aliases) for a scanning pass, longest-first."""
    forms: List[str] = []
    for canonical, _t, aliases in _GAZETTEER:
        forms.append(canonical)
        forms.extend(aliases)
    return sorted(set(forms), key=len, reverse=True)


# ---------------------------------------------------------------- relationship cue patterns (Step 4)
# ordered: first match wins. Each maps a cue (found in the text BETWEEN two entities) → rel_type.
RELATION_CUES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(is built on|built on top of|built on|based on|inspired by)\b", re.I), "inspired_by"),
    (re.compile(r"\b(created by|developed by|written by|authored by|invented by|made by)\b", re.I), "created_by"),
    (re.compile(r"\b(depends on|requires|needs|relies on)\b", re.I), "depends_on"),
    (re.compile(r"\b(implements|implementing)\b", re.I), "implements"),
    (re.compile(r"\b(extends|inherits from|subclass(es)? of)\b", re.I), "extends"),
    (re.compile(r"\b(is part of|part of|belongs to|component of|module of)\b", re.I), "part_of"),
    (re.compile(r"\b(calls|invokes|executes)\b", re.I), "calls"),
    (re.compile(r"\b(references|cites|refers to)\b", re.I), "references"),
    (re.compile(r"\b(defines|introduces)\b", re.I), "defines"),
    (re.compile(r"\b(explains|describes|discusses)\b", re.I), "explains"),
    (re.compile(r"\b(compared (to|with)|versus|vs\.?)\b", re.I), "compared_with"),
    (re.compile(r"\b(prerequisite (for|of)|required before)\b", re.I), "prerequisite"),
    (re.compile(r"\b(uses|utili[sz]es|leverages|powered by|built with|via)\b", re.I), "uses"),
    (re.compile(r"\b(supports|enables)\b", re.I), "supports"),
    (re.compile(r"\b(is an?|are)\b", re.I), "is_a"),
]


def classify_cue(between: str) -> str:
    for rx, rtype in RELATION_CUES:
        if rx.search(between):
            return rtype
    return "related_to"
