"""Graph Reasoning & Explainable AI interfaces (Phase 7, Module 3).

Where Module 2 RETRIEVES a neighborhood, this module REASONS over it: it finds multi-hop reasoning
paths, infers implicit relationships (transitive rules), propagates confidence through the paths,
verifies conclusions against evidence (reusing the Phase-6 Verification Engine), and emits STRUCTURED,
explainable reasoning metadata (never chain-of-thought). Everything is interface-driven so a future GNN
/ graph-reasoning model plugs in without touching the orchestrator.

Value objects:
- `ReasoningPath`        — an ordered entity/relationship chain (A —uses→ B —depends_on→ C) + confidence.
- `ReasonedRelationship`— an INFERRED edge (kept separate from extracted edges) + its derivation.
- `DependencyChain`     — a directed dependency/root-cause chain.
- `ReasoningResult`     — the full result (paths + inferences + confidence + verification + explanation).

Confidence reuses the Phase-6 `ConfidenceBreakdown`/`ConfidenceSignal` value objects (no duplication).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class PathEdge:
    rel_id: str
    rel_type: str
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    weight: float = 1.0
    confidence: float = 0.5
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"rel_id": self.rel_id, "rel_type": self.rel_type, "source": self.source_name,
                "target": self.target_name, "weight": round(self.weight, 4),
                "confidence": round(self.confidence, 4)}


@dataclass
class ReasoningPath:
    node_ids: List[str]
    node_names: List[str]
    edges: List[PathEdge]
    path_confidence: float = 0.0
    weight: float = 0.0

    @property
    def length(self) -> int:
        return len(self.edges)

    @property
    def relationship_chain(self) -> str:
        parts = [self.node_names[0]] if self.node_names else []
        for e in self.edges:
            parts.append(f"—{e.rel_type}→"); parts.append(e.target_name)
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": self.node_names, "chain": self.relationship_chain,
                "edges": [e.to_dict() for e in self.edges], "length": self.length,
                "path_confidence": round(self.path_confidence, 4), "weight": round(self.weight, 4)}


@dataclass
class ReasonedRelationship:
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    rel_type: str                          # the INFERRED relationship type (e.g. depends_on)
    confidence: float
    hops: int
    derivation: str                        # the path it was inferred from
    via: List[str] = field(default_factory=list)   # intermediate node names
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def key(self):
        return (self.source_id, self.target_id, self.rel_type)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source_name, "target": self.target_name, "rel_type": self.rel_type,
                "confidence": round(self.confidence, 4), "hops": self.hops, "derivation": self.derivation,
                "via": self.via, "inferred": True}


@dataclass
class DependencyChain:
    root: str                              # the entity being analyzed
    root_name: str
    chain: List[str]                       # ordered entity names (root → … → leaf)
    rel_types: List[str]
    depth: int
    confidence: float
    is_root_cause: bool = False            # the leaf is a terminal dependency

    def to_dict(self) -> Dict[str, Any]:
        return {"root": self.root_name, "chain": self.chain, "rel_types": self.rel_types,
                "depth": self.depth, "confidence": round(self.confidence, 4),
                "is_root_cause": self.is_root_cause}


@dataclass
class ReasoningResult:
    query: str
    seeds: List[Dict[str, Any]] = field(default_factory=list)
    paths: List[ReasoningPath] = field(default_factory=list)
    inferences: List[ReasonedRelationship] = field(default_factory=list)
    dependencies: List[DependencyChain] = field(default_factory=list)
    root_causes: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Any = None                 # Phase-6 ConfidenceBreakdown
    verification: Optional[Dict[str, Any]] = None
    explanation: Dict[str, Any] = field(default_factory=dict)
    context_text: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    complexity: Dict[str, int] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query, "seeds": self.seeds,
            "paths": [p.to_dict() for p in self.paths], "inferences": [r.to_dict() for r in self.inferences],
            "dependencies": [d.to_dict() for d in self.dependencies], "root_causes": self.root_causes,
            "confidence": self.confidence.to_dict() if self.confidence is not None else None,
            "verification": self.verification, "explanation": self.explanation,
            "context_text": self.context_text, "citations": self.citations,
            "complexity": self.complexity, "timings": self.timings, "cache_hit": self.cache_hit,
        }


# --------------------------------------------------------------------- protocols
class PathReasoner(Protocol):
    def find_paths(self, adjacency, seeds: List[str], *, hops: int, directed: bool,
                   max_paths: int) -> List[ReasoningPath]: ...


class RelationshipInferer(Protocol):
    def infer(self, paths: List[ReasoningPath]) -> List[ReasonedRelationship]: ...


class ConfidencePropagator(Protocol):
    def propagate(self, paths, inferences, *, node_index, signals_in) -> Any: ...


class ExplanationBuilder(Protocol):
    def build(self, result: ReasoningResult) -> Dict[str, Any]: ...
