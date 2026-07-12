"""Graph Builder (Steps 2, 6, 9, 11) — the extract → resolve → dedup → version → store → validate core.

Interface-driven: takes a `GraphStore` + injectable extractors/validator (defaults are the deterministic
implementations). It builds INCREMENTALLY (Step 15): existing workspace entities seed the resolver, so a
new document merges into the existing canonical nodes instead of rebuilding the graph. Provenance is
preserved (source_refs union + edge evidence) and versioning is a monotonic `version` bump on every
merge/update. Emits graph events + returns per-build counts + a validation report for the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.knowledge.events import InMemoryGraphEvents
from app.knowledge.extraction import EntityExtractor, ExtractedEntity, RelationshipExtractor
from app.knowledge.models import GraphEntity, GraphRelationship
from app.knowledge.repository import new_id
from app.knowledge.resolution import GraphResolver
from app.knowledge.sources import TextSource
from app.knowledge.validation import normalize_name
from app.knowledge.validator import GraphValidator

_MAX_SOURCE_REFS = 25
_MAX_EVIDENCE = 8


@dataclass
class BuildResult:
    entities_extracted: int = 0
    entities_created: int = 0
    entities_merged: int = 0
    relationships_extracted: int = 0
    relationships_created: int = 0
    relationships_merged: int = 0
    duplicates_merged: int = 0
    sources_processed: int = 0
    confidences: List[float] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)
    events: Dict[str, int] = field(default_factory=dict)

    @property
    def avg_confidence(self) -> float:
        return round(sum(self.confidences) / len(self.confidences), 4) if self.confidences else 0.0


class GraphBuilder:
    pipeline_version = "graph-v1"

    def __init__(self, store, *, entity_extractor=None, relationship_extractor=None, validator=None):
        self.store = store
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.relationship_extractor = relationship_extractor or RelationshipExtractor()
        self.validator = validator or GraphValidator()

    def build(self, workspace_id: str, owner_id: str, sources: List[TextSource]) -> BuildResult:
        result = BuildResult()
        events = InMemoryGraphEvents()
        existing = self.store.workspace_entities(workspace_id, owner_id)
        resolver = GraphResolver(existing)
        name_index: Dict[str, GraphEntity] = {}   # normalized name/alias -> GraphEntity (this build)
        for e in existing:
            name_index[normalize_name(e.canonical_name)] = e
            for a in (e.aliases or []):
                name_index[normalize_name(a)] = e

        for src in sources:
            if not (src.text or "").strip():
                continue
            result.sources_processed += 1
            extracted = self.entity_extractor.extract(src.text, src.source_ref)
            for ex in extracted:
                result.entities_extracted += 1
                ent = self._upsert_entity(workspace_id, owner_id, ex, resolver, result, events)
                name_index[normalize_name(ex.canonical_name)] = ent
                for a in ex.aliases:
                    name_index.setdefault(normalize_name(a), ent)
                result.confidences.append(ent.confidence)

            for rx in self.relationship_extractor.extract(src.text, extracted, src.source_ref):
                result.relationships_extracted += 1
                s = name_index.get(normalize_name(rx.source_name))
                t = name_index.get(normalize_name(rx.target_name))
                if not s or not t or s.id == t.id:
                    continue
                self._upsert_relationship(workspace_id, owner_id, s, t, rx, result, events)

        self.store.commit()
        self._recompute_degrees(workspace_id, owner_id)
        self.store.commit()

        entities_all = self.store.workspace_entities(workspace_id, owner_id)
        rels_all = self.store.workspace_relationships(workspace_id, owner_id)
        report = self.validator.validate(entities_all, rels_all)
        events.emit("validated", {"ok": report.ok, "errors": len(report.errors)})
        result.report = report.to_dict()
        result.events = events.summary()
        return result

    # ------------------------------------------------------------------ entity upsert (resolve + dedup + version)
    def _upsert_entity(self, ws: str, owner: str, ex: ExtractedEntity, resolver: GraphResolver,
                       result: BuildResult, events) -> GraphEntity:
        match = resolver.match(ex)
        if match is not None:
            changed = self._merge_entity(match, ex)
            if changed:
                match.version += 1
                self.store.update_entity(match)
                result.entities_merged += 1
                result.duplicates_merged += 1
                events.emit("entity_merged", {"id": match.id, "name": match.canonical_name})
            return match
        ent = GraphEntity(
            id=new_id("ent"), workspace_id=ws, owner_id=owner, entity_type=ex.entity_type,
            canonical_name=ex.canonical_name, normalized_name=normalize_name(ex.canonical_name),
            aliases=list(dict.fromkeys(ex.aliases)), confidence=round(ex.confidence, 4), mention_count=1,
            source_refs=[ex.source_ref] if ex.source_ref else [], version=1, status="active")
        self.store.add_entity(ent)
        resolver.register_new(ent)
        result.entities_created += 1
        events.emit("entity_created", {"id": ent.id, "name": ent.canonical_name, "type": ent.entity_type})
        return ent

    @staticmethod
    def _merge_entity(entity: GraphEntity, ex: ExtractedEntity) -> bool:
        changed = False
        aliases = list(entity.aliases or [])
        for a in [ex.canonical_name, *ex.aliases]:
            if a and normalize_name(a) != entity.normalized_name and a not in aliases:
                aliases.append(a); changed = True
        entity.aliases = aliases[:50]
        refs = list(entity.source_refs or [])
        if ex.source_ref and ex.source_ref not in refs:
            refs.append(ex.source_ref); changed = True
        entity.source_refs = refs[-_MAX_SOURCE_REFS:]
        entity.mention_count = (entity.mention_count or 0) + 1
        if ex.confidence > (entity.confidence or 0):
            entity.confidence = round(ex.confidence, 4); changed = True
        # a more specific type beats a generic 'concept'
        if entity.entity_type == "concept" and ex.entity_type != "concept":
            entity.entity_type = ex.entity_type; changed = True
        return changed or True   # mention_count always changes → always an update

    # ------------------------------------------------------------------ relationship upsert
    def _upsert_relationship(self, ws: str, owner: str, s: GraphEntity, t: GraphEntity, rx,
                             result: BuildResult, events) -> None:
        existing = self.store.find_relationship(ws, s.id, t.id, rx.rel_type)
        if existing is not None:
            existing.mention_count += 1
            existing.weight = round(min(1.0, existing.weight + 0.1), 4)
            ev = list(existing.evidence or [])
            if rx.evidence and rx.evidence not in ev:
                ev.append(rx.evidence)
            existing.evidence = ev[-_MAX_EVIDENCE:]
            existing.version += 1
            self.store.update_relationship(existing)
            result.relationships_merged += 1
            return
        rel = GraphRelationship(
            id=new_id("rel"), workspace_id=ws, owner_id=owner, source_id=s.id, target_id=t.id,
            rel_type=rx.rel_type, directed=True, weight=round(rx.weight, 4), confidence=round(rx.confidence, 4),
            mention_count=1, evidence=[rx.evidence] if rx.evidence else [], version=1, status="active")
        self.store.add_relationship(rel)
        result.relationships_created += 1
        events.emit("relationship_created", {"id": rel.id, "type": rel.rel_type})

    def _recompute_degrees(self, ws: str, owner: str) -> None:
        entities = self.store.workspace_entities(ws, owner)
        rels = self.store.workspace_relationships(ws, owner)
        degree: Dict[str, int] = {}
        for r in rels:
            degree[r.source_id] = degree.get(r.source_id, 0) + 1
            degree[r.target_id] = degree.get(r.target_id, 0) + 1
        for e in entities:
            d = degree.get(e.id, 0)
            if e.degree != d:
                e.degree = d
                self.store.update_entity(e)
