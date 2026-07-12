"""Entity + Relationship extraction (Steps 3–4) — deterministic, LLM-free, testable.

Mirrors the project's pattern (deterministic engines that work everywhere, with an injected engine seam
for a future spaCy/LLM upgrade). Extraction combines three signals:

- gazetteer      — high-confidence typing + canonicalization of known technical entities.
- acronym defs   — "Large Language Model (LLM)" → canonical + alias (feeds resolution).
- proper nouns   — capitalized multi-word spans → candidate concepts/orgs/people (lower confidence).

Relationships come from entity co-occurrence within a sentence: the text BETWEEN two entities is matched
against relationship cue patterns ("uses", "depends on", …) → a typed, directed edge; otherwise a
weak `related_to`. Every entity/edge carries provenance (source ref + evidence sentence).

`EntityExtractor`/`RelationshipExtractor` are the injectable extraction interfaces — a future model-based
extractor implements the same `extract(...)` shape without touching the builder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.knowledge import gazetteer
from app.knowledge.validation import normalize_name
from app.reasoning.textutil import sentences  # reuse Module-3 sentence splitter (no duplication)

_ACRONYM_DEF = re.compile(r"\b([A-Z][A-Za-z0-9.+\-]*(?:\s+[A-Za-z0-9.+\-]+){0,5})\s*\(([A-Za-z]{2,8}s?)\)")
_PROPER = re.compile(r"\b([A-Z][a-zA-Z0-9.+\-]*(?:\s+[A-Z][a-zA-Z0-9.+\-]*)+)\b")
_ORG_HINT = re.compile(r"\b(Inc|Corp|LLC|Ltd|University|Institute|Labs?|Foundation|Team)\b")

_STOP_CAPS = {"The", "This", "That", "These", "Those", "It", "In", "On", "For", "And", "But", "We",
              "You", "They", "He", "She", "There", "Here", "When", "Where", "Why", "How", "What",
              "A", "An", "As", "At", "By", "Of", "To", "If", "So", "Page", "Second", "First", "Next",
              "Figure", "Table", "Section", "Chapter", "Note"}


@dataclass
class ExtractedEntity:
    canonical_name: str
    entity_type: str
    aliases: List[str] = field(default_factory=list)
    confidence: float = 0.5
    source_ref: Dict[str, Any] = field(default_factory=dict)
    surfaces: List[str] = field(default_factory=list)   # surface forms seen (for relationship matching)


@dataclass
class ExtractedRelationship:
    source_name: str
    target_name: str
    rel_type: str
    weight: float = 0.5
    confidence: float = 0.5
    evidence: Dict[str, Any] = field(default_factory=dict)


def _trim_phrase(phrase: str) -> str:
    """Keep the trailing capitalized phrase (drop leading stopwords), max 6 words."""
    words = (phrase or "").strip().split()
    while words and words[0] in _STOP_CAPS:
        words = words[1:]
    return " ".join(words[-6:])


def _occurs(surface: str, text: str) -> List[Tuple[int, int]]:
    """Case-insensitive occurrences of `surface` in `text`, respecting rough word boundaries."""
    spans = []
    for m in re.finditer(re.escape(surface), text, re.I):
        s, e = m.start(), m.end()
        before = text[s - 1] if s > 0 else " "
        after = text[e] if e < len(text) else " "
        if not before.isalnum() and not after.isalnum():
            spans.append((s, e))
    return spans


class EntityExtractor:
    name = "deterministic-v1"

    def extract(self, text: str, source_ref: Optional[Dict[str, Any]] = None) -> List[ExtractedEntity]:
        source_ref = source_ref or {}
        found: Dict[str, ExtractedEntity] = {}   # normalized canonical -> entity

        def _add(canonical: str, etype: str, conf: float, surface: str, aliases: Optional[List[str]] = None):
            key = normalize_name(canonical)
            if not key:
                return
            ent = found.get(key)
            if ent is None:
                ent = ExtractedEntity(canonical_name=canonical, entity_type=etype, confidence=conf,
                                      source_ref=source_ref, aliases=list(aliases or []), surfaces=[])
                found[key] = ent
            else:
                ent.confidence = max(ent.confidence, conf)
                for a in (aliases or []):
                    if a not in ent.aliases:
                        ent.aliases.append(a)
                if etype != "concept" and ent.entity_type == "concept":
                    ent.entity_type = etype
            if surface and surface not in ent.surfaces:
                ent.surfaces.append(surface)

        # process per-SENTENCE so regex spans never cross sentence boundaries
        for sent in sentences(text or ""):
            # 1) acronym definitions — canonical = phrase (trimmed), alias = acronym
            for m in _ACRONYM_DEF.finditer(sent):
                phrase = _trim_phrase(m.group(1))
                acro = m.group(2).strip()
                if not phrase:
                    continue
                resolved = gazetteer.resolve(phrase) or gazetteer.resolve(acro)
                canonical, etype = resolved if resolved else (phrase, "concept")
                alias_list = [acro] + ([phrase] if normalize_name(canonical) != normalize_name(phrase) else [])
                _add(canonical, etype, 0.85, phrase, aliases=alias_list)
                _add(canonical, etype, 0.85, acro)

            # 2) gazetteer scan (longest surface first so multi-word wins)
            for surface in gazetteer.surface_forms():
                if _occurs(surface, sent):
                    resolved = gazetteer.resolve(surface)
                    if resolved:
                        canonical, etype = resolved
                        aliases = [surface] if normalize_name(surface) != normalize_name(canonical) else []
                        _add(canonical, etype, 0.9, surface, aliases=aliases)

            # 3) proper-noun spans (candidate concepts/orgs/people) — lower confidence
            for m in _PROPER.finditer(sent):
                words = m.group(1).strip().split()
                while words and words[0] in _STOP_CAPS:
                    words = words[1:]
                span = " ".join(words)
                if len(words) < 2 or words[0] in _STOP_CAPS:
                    continue
                if gazetteer.resolve(span):   # already covered by the gazetteer
                    continue
                etype = "organization" if _ORG_HINT.search(span) else "concept"
                _add(span, etype, 0.5, span)

        return list(found.values())


class RelationshipExtractor:
    name = "cooccurrence-v1"

    def extract(self, text: str, entities: List[ExtractedEntity],
                source_ref: Optional[Dict[str, Any]] = None) -> List[ExtractedRelationship]:
        source_ref = source_ref or {}
        if len(entities) < 2:
            return []
        # surface -> canonical (include canonical + aliases + seen surfaces)
        surface_map: List[Tuple[str, str]] = []
        for e in entities:
            forms = set([e.canonical_name, *e.aliases, *e.surfaces])
            for f in forms:
                if f and len(f) >= 2:
                    surface_map.append((f, e.canonical_name))
        surface_map.sort(key=lambda t: len(t[0]), reverse=True)

        rels: Dict[Tuple[str, str, str], ExtractedRelationship] = {}
        for sent in sentences(text):
            hits: List[Tuple[int, int, str]] = []   # (start, end, canonical)
            claimed: List[Tuple[int, int]] = []
            for surface, canonical in surface_map:
                for s, e in _occurs(surface, sent):
                    if any(not (e <= cs or s >= ce) for cs, ce in claimed):
                        continue   # overlapping span already claimed by a longer surface
                    claimed.append((s, e)); hits.append((s, e, canonical))
            hits.sort(key=lambda h: h[0])
            for (s1, e1, c1), (s2, e2, c2) in zip(hits, hits[1:]):
                if c1 == c2:
                    continue
                between = sent[e1:s2]
                if len(between) > 80:
                    continue
                rtype = gazetteer.classify_cue(between)
                weight = 0.4 if rtype == "related_to" else 0.75
                key = (c1, c2, rtype)
                r = rels.get(key)
                if r is None:
                    rels[key] = ExtractedRelationship(
                        source_name=c1, target_name=c2, rel_type=rtype, weight=weight,
                        confidence=weight, evidence={"text": sent[:400], **source_ref})
                else:
                    r.weight = min(1.0, r.weight + 0.1)
        return list(rels.values())
