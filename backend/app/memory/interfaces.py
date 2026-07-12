"""Semantic Memory & Graph Retrieval interfaces (Phase 7, Module 2).

The knowledge graph (Module 1) becomes a FIRST-CLASS retrieval source: a query is resolved to canonical
graph entities, the graph is traversed into a semantic neighborhood, graph hits are scored, and fused
with vector/sparse/multimodal/temporal retrieval through the EXISTING Phase-4 fusion (`graph` is just a
new modality). Everything is interface-driven so new graph retrievers / traversal strategies / scorers
plug in without touching the orchestrator.

Value objects:
- `GraphHit`      — one retrieved unit of KNOWLEDGE (entity / neighbor / relationship / evidence / …),
                    with hop distance, an explainable score, and provenance. Converts to a Phase-4
                    `RetrievalHit` (modality="graph") for reuse of the existing fusion.
- `Neighborhood`  — the traversal result: nodes + edges + per-node hop distance from the seeds.
- `MemoryQuery`   — the resolved retrieval request (seeds + traversal config + limits).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

GRAPH_MODALITY = "graph"
HIT_KINDS = ("entity", "neighbor", "relationship", "evidence", "topic", "concept", "backlink", "reference")


@dataclass
class GraphHit:
    kind: str                              # one of HIT_KINDS
    key: str                               # dedup key (ent:<id> / rel:<id>)
    text: str                              # the knowledge statement / entity summary
    entity_id: Optional[str] = None
    rel_id: Optional[str] = None
    canonical_name: Optional[str] = None
    entity_type: Optional[str] = None
    rel_type: Optional[str] = None
    source_name: Optional[str] = None
    target_name: Optional[str] = None
    hop_distance: int = 0
    base_score: float = 0.5
    score: float = 0.0                     # after MemoryScorer
    signals: Dict[str, float] = field(default_factory=dict)
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    rank_in_modality: int = 0

    def citation(self, index: int) -> Dict[str, Any]:
        return {"index": index, "kind": self.kind, "entity_id": self.entity_id, "rel_id": self.rel_id,
                "name": self.canonical_name, "entity_type": self.entity_type, "rel_type": self.rel_type,
                "text": self.text[:300], "hop_distance": self.hop_distance,
                "confidence": round(self.score, 4), "provenance": self.provenance[:3]}

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "text": self.text[:400],
                "entity_id": self.entity_id, "rel_id": self.rel_id, "canonical_name": self.canonical_name,
                "entity_type": self.entity_type, "rel_type": self.rel_type, "source_name": self.source_name,
                "target_name": self.target_name, "hop_distance": self.hop_distance,
                "score": round(self.score, 4), "signals": {k: round(v, 4) for k, v in self.signals.items()}}

    def to_retrieval_hit(self):
        """Adapt to a Phase-4 RetrievalHit so the EXISTING fusion can rank graph alongside vectors."""
        from app.mmretrieval.schemas import RetrievalHit
        doc = (self.provenance[0].get("document_id") if self.provenance else None)
        return RetrievalHit(
            key=self.key, modality=GRAPH_MODALITY, source_type=f"graph_{self.kind}", document_id=doc,
            content=self.text, title=self.canonical_name or "", chunk_id=self.rel_id or self.entity_id,
            raw_score=self.score, normalized_score=min(1.0, self.score), rank_in_modality=self.rank_in_modality,
            confidence=round(self.score, 4),
            metadata={"kind": self.kind, "hop_distance": self.hop_distance, "rel_type": self.rel_type,
                      "signals": self.signals})


@dataclass
class Neighborhood:
    seeds: List[str] = field(default_factory=list)                 # seed entity ids
    nodes: Dict[str, Any] = field(default_factory=dict)            # id -> GraphEntity
    edges: List[Any] = field(default_factory=list)                 # GraphRelationship
    hop: Dict[str, int] = field(default_factory=dict)             # id -> distance from nearest seed
    truncated: bool = False

    @property
    def size(self) -> int:
        return len(self.nodes)


@dataclass
class MemoryQuery:
    query: str
    workspace_id: str
    owner_id: str
    seed_entity_ids: List[str] = field(default_factory=list)
    hops: int = 2
    strategy: str = "bfs"                  # bfs | dfs
    rel_types: Optional[List[str]] = None   # relationship filter
    max_nodes: int = 60
    limit: int = 20                         # hits returned
    hybrid: bool = False                    # fuse with vector retrieval
    document_id: Optional[str] = None


# --------------------------------------------------------------------- protocols
class EntityRecognizer(Protocol):
    def recognize(self, query: str, workspace_id: str, owner_id: str) -> List[Any]: ...


class TraversalStrategy(Protocol):
    name: str
    def expand(self, repo, workspace_id: str, owner_id: str, seeds: List[str], *, hops: int,
               rel_types: Optional[List[str]], max_nodes: int) -> Neighborhood: ...


class GraphRetriever(Protocol):
    kind: str
    def retrieve(self, ctx) -> List[GraphHit]: ...


class MemoryScorer(Protocol):
    def score(self, hit: GraphHit, ctx) -> GraphHit: ...
