"""Relationship Inference (Step 4) — derive implicit edges from reasoning paths (transitive rules).

Applies a deterministic composition table to each reasoning path: if consecutive edges compose (e.g.
`uses ∘ depends_on → depends_on`, `depends_on ∘ depends_on → depends_on`, `part_of ∘ part_of → part_of`),
an INFERRED relationship between the path's endpoints is derived, with a confidence that decays with hop
distance and multiplies the edge confidences. Inferred relationships are kept SEPARATE from extracted
ones (persisted with `status="inferred"`, invisible to retrieval) and carry their derivation for
explainability. A future GNN/rule-learner plugs in behind the `RelationshipInferer` protocol.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.graphreason.interfaces import ReasonedRelationship, ReasoningPath

# (rel_a, rel_b) -> inferred rel; the whole chain must reduce to a single relation to infer.
COMPOSE: Dict[Tuple[str, str], str] = {
    ("depends_on", "depends_on"): "depends_on",
    ("uses", "depends_on"): "depends_on",
    ("uses", "uses"): "uses",
    ("part_of", "part_of"): "part_of",
    ("is_a", "is_a"): "is_a",
    ("is_a", "part_of"): "part_of",
    ("prerequisite", "prerequisite"): "prerequisite",
    ("extends", "extends"): "extends",
    ("implements", "extends"): "implements",
    ("references", "references"): "references",
    ("inspired_by", "inspired_by"): "inspired_by",
    ("uses", "part_of"): "depends_on",
    ("depends_on", "part_of"): "depends_on",
}

INFER_DECAY = 0.85


def _reduce_chain(rel_types: List[str]) -> str | None:
    """Fold a chain of relationships into a single inferred relation, or None if it doesn't compose."""
    if not rel_types:
        return None
    acc = rel_types[0]
    for nxt in rel_types[1:]:
        composed = COMPOSE.get((acc, nxt))
        if composed is None:
            return None
        acc = composed
    return acc


class RelationshipInference:
    name = "transitive-v1"

    def infer(self, paths: List[ReasoningPath]) -> List[ReasonedRelationship]:
        out: Dict[Tuple[str, str, str], ReasonedRelationship] = {}
        for p in paths:
            if p.length < 2:      # a 1-hop path is an explicit edge, not an inference
                continue
            rel_types = [e.rel_type for e in p.edges]
            inferred = _reduce_chain(rel_types)
            if inferred is None:
                continue
            src, tgt = p.node_ids[0], p.node_ids[-1]
            if src == tgt:
                continue
            conf = round(p.path_confidence * INFER_DECAY, 6)
            via = p.node_names[1:-1]
            rr = ReasonedRelationship(
                source_id=src, target_id=tgt, source_name=p.node_names[0], target_name=p.node_names[-1],
                rel_type=inferred, confidence=conf, hops=p.length, derivation=p.relationship_chain, via=via,
                evidence=[e.to_dict() for e in p.edges])
            existing = out.get(rr.key)
            if existing is None or conf > existing.confidence:
                out[rr.key] = rr
        return sorted(out.values(), key=lambda r: r.confidence, reverse=True)
