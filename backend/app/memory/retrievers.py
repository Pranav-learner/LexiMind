"""Graph Retrievers (Step 4) — read a semantic neighborhood into ranked knowledge hits.

Eight retrievers behind ONE common interface (`kind` + `retrieve(ctx) -> List[GraphHit]`), mirroring the
Phase-4 multimodal retriever design so graph retrieval slots into the same fusion:

- entity        — the resolved seed concepts themselves.
- neighbor      — entities reached by traversal (hop ≥ 1).
- relationship  — typed edges in the neighborhood ("React —uses→ JavaScript").
- evidence      — the supporting sentences attached to edges.
- topic         — concept/topic nodes around the seeds.
- concept       — the most central (highest-degree) nodes in the neighborhood.
- backlink      — incoming edges (what points AT a seed).
- reference     — reference/created_by/inspired_by edges from the seeds.

Retrievers are pure reads over the traversed `Neighborhood` (no new DB round-trips) and carry provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.memory.interfaces import GraphHit, Neighborhood

_REFERENCE_TYPES = {"references", "created_by", "inspired_by", "prerequisite", "compared_with"}


@dataclass
class RetrieverContext:
    query: str
    seeds: List[Any]                       # GraphEntity seeds
    neighborhood: Neighborhood

    @property
    def seed_ids(self):
        return {s.id for s in self.seeds}


def _entity_summary(e) -> str:
    bits = [e.canonical_name]
    if e.entity_type:
        bits.append(f"({e.entity_type})")
    if e.aliases:
        bits.append("aka " + ", ".join(e.aliases[:4]))
    return " ".join(bits)


def _entity_prov(e) -> List[Dict[str, Any]]:
    return list(e.source_refs or [])[:3]


class EntityRetriever:
    kind = "entity"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        return [GraphHit(kind="entity", key=f"ent:{e.id}", text=_entity_summary(e), entity_id=e.id,
                         canonical_name=e.canonical_name, entity_type=e.entity_type, hop_distance=0,
                         base_score=0.9, provenance=_entity_prov(e)) for e in ctx.seeds]


class NeighborhoodRetriever:
    kind = "neighbor"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        out = []
        for nid, e in ctx.neighborhood.nodes.items():
            hop = ctx.neighborhood.hop.get(nid, 1)
            if hop == 0:
                continue
            out.append(GraphHit(kind="neighbor", key=f"ent:{e.id}", text=_entity_summary(e), entity_id=e.id,
                                canonical_name=e.canonical_name, entity_type=e.entity_type, hop_distance=hop,
                                base_score=0.6, provenance=_entity_prov(e)))
        return out


class RelationshipRetriever:
    kind = "relationship"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        nodes = ctx.neighborhood.nodes
        out = []
        for r in ctx.neighborhood.edges:
            s = nodes.get(r.source_id); t = nodes.get(r.target_id)
            if not s or not t:
                continue
            hop = min(ctx.neighborhood.hop.get(r.source_id, 9), ctx.neighborhood.hop.get(r.target_id, 9))
            out.append(GraphHit(kind="relationship", key=f"rel:{r.id}",
                                text=f"{s.canonical_name} —{r.rel_type}→ {t.canonical_name}", rel_id=r.id,
                                rel_type=r.rel_type, source_name=s.canonical_name, target_name=t.canonical_name,
                                hop_distance=hop, base_score=min(0.85, 0.55 + r.weight * 0.3),
                                provenance=list(r.evidence or [])[:2],
                                signals={"rel_weight": r.weight, "rel_confidence": r.confidence}))
        return out


class EvidenceRetriever:
    kind = "evidence"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        nodes = ctx.neighborhood.nodes
        out = []
        for r in ctx.neighborhood.edges:
            for ev in (r.evidence or [])[:2]:
                text = (ev.get("text") or "").strip()
                if not text:
                    continue
                s = nodes.get(r.source_id); t = nodes.get(r.target_id)
                hop = min(ctx.neighborhood.hop.get(r.source_id, 9), ctx.neighborhood.hop.get(r.target_id, 9))
                out.append(GraphHit(kind="evidence", key=f"rel:{r.id}:ev", text=text, rel_id=r.id,
                                    rel_type=r.rel_type, source_name=s.canonical_name if s else None,
                                    target_name=t.canonical_name if t else None, hop_distance=hop,
                                    base_score=0.65, provenance=[ev]))
        return out


class TopicRetriever:
    kind = "topic"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        out = []
        for nid, e in ctx.neighborhood.nodes.items():
            if e.entity_type in ("concept", "paper", "book") and ctx.neighborhood.hop.get(nid, 0) >= 1:
                out.append(GraphHit(kind="topic", key=f"ent:{e.id}", text=_entity_summary(e), entity_id=e.id,
                                    canonical_name=e.canonical_name, entity_type=e.entity_type,
                                    hop_distance=ctx.neighborhood.hop.get(nid, 1), base_score=0.55,
                                    provenance=_entity_prov(e)))
        return out


class ConceptRetriever:
    kind = "concept"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        ranked = sorted(ctx.neighborhood.nodes.values(), key=lambda e: e.degree, reverse=True)
        out = []
        for e in ranked[:8]:
            if e.id in ctx.seed_ids:
                continue
            out.append(GraphHit(kind="concept", key=f"ent:{e.id}", text=_entity_summary(e), entity_id=e.id,
                                canonical_name=e.canonical_name, entity_type=e.entity_type,
                                hop_distance=ctx.neighborhood.hop.get(e.id, 1), base_score=0.55,
                                provenance=_entity_prov(e), signals={"degree": float(e.degree)}))
        return out


class BacklinkRetriever:
    kind = "backlink"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        nodes = ctx.neighborhood.nodes
        seed_ids = ctx.seed_ids
        out = []
        for r in ctx.neighborhood.edges:
            if r.target_id in seed_ids and r.source_id in nodes:  # incoming edge to a seed
                s = nodes[r.source_id]; t = nodes.get(r.target_id)
                out.append(GraphHit(kind="backlink", key=f"rel:{r.id}:bl",
                                    text=f"{s.canonical_name} —{r.rel_type}→ {t.canonical_name if t else '?'}",
                                    rel_id=r.id, rel_type=r.rel_type, source_name=s.canonical_name,
                                    target_name=t.canonical_name if t else None, hop_distance=1,
                                    base_score=0.6, provenance=list(r.evidence or [])[:1]))
        return out


class ReferenceRetriever:
    kind = "reference"

    def retrieve(self, ctx: RetrieverContext) -> List[GraphHit]:
        nodes = ctx.neighborhood.nodes
        seed_ids = ctx.seed_ids
        out = []
        for r in ctx.neighborhood.edges:
            if r.rel_type in _REFERENCE_TYPES and (r.source_id in seed_ids or r.target_id in seed_ids):
                s = nodes.get(r.source_id); t = nodes.get(r.target_id)
                if not s or not t:
                    continue
                out.append(GraphHit(kind="reference", key=f"rel:{r.id}:ref",
                                    text=f"{s.canonical_name} —{r.rel_type}→ {t.canonical_name}", rel_id=r.id,
                                    rel_type=r.rel_type, source_name=s.canonical_name,
                                    target_name=t.canonical_name, hop_distance=1, base_score=0.62,
                                    provenance=list(r.evidence or [])[:1]))
        return out


ALL_RETRIEVERS = [EntityRetriever(), NeighborhoodRetriever(), RelationshipRetriever(), EvidenceRetriever(),
                  TopicRetriever(), ConceptRetriever(), BacklinkRetriever(), ReferenceRetriever()]
