"""Graph Validation (Step 10) — integrity checks over a built/loaded graph → a structured report.

Deterministic checks:
- broken relationships  — an edge whose source/target entity is missing/inactive (error).
- invalid types         — entity/relationship type outside the known vocabulary (error).
- invalid self-loops    — source == target for a type where that is meaningless (error).
- duplicate edges       — same (source, target, type) appearing more than once (warning).
- orphan nodes          — an active entity with no relationships (warning — often fine early on).

Runs over in-memory entities/edges (during a build) or a loaded workspace slice (via the API).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.knowledge.models import GraphEntity, GraphRelationship
from app.knowledge.validation import (
    NO_SELF_LOOP, is_valid_entity_type, is_valid_relationship_type,
)


@dataclass
class ValidationReport:
    ok: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)

    def _err(self, kind: str, detail: str, ref: str = "") -> None:
        self.errors.append({"kind": kind, "detail": detail, "ref": ref}); self.ok = False

    def _warn(self, kind: str, detail: str, ref: str = "") -> None:
        self.warnings.append({"kind": kind, "detail": detail, "ref": ref})

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors[:200], "warnings": self.warnings[:200],
                "error_count": len(self.errors), "warning_count": len(self.warnings), "counts": self.counts}


class GraphValidator:
    name = "graph-validator-v1"

    def validate(self, entities: List[GraphEntity], relationships: List[GraphRelationship]) -> ValidationReport:
        report = ValidationReport()
        active_ids = {e.id for e in entities if e.status == "active"}

        for e in entities:
            if not is_valid_entity_type(e.entity_type):
                report._err("invalid_entity_type", f"Entity '{e.canonical_name}' has type '{e.entity_type}'.", e.id)

        edge_keys: Counter = Counter()
        degree: Counter = Counter()
        for r in relationships:
            if r.status != "active":
                continue
            if not is_valid_relationship_type(r.rel_type):
                report._err("invalid_relationship_type", f"Edge has type '{r.rel_type}'.", r.id)
            if r.source_id not in active_ids or r.target_id not in active_ids:
                report._err("broken_relationship",
                            f"Edge {r.rel_type} references a missing/inactive endpoint.", r.id)
            if r.source_id == r.target_id and r.rel_type in NO_SELF_LOOP:
                report._err("invalid_self_loop", f"Self-loop with type '{r.rel_type}'.", r.id)
            edge_keys[(r.source_id, r.target_id, r.rel_type)] += 1
            degree[r.source_id] += 1; degree[r.target_id] += 1

        for key, n in edge_keys.items():
            if n > 1:
                report._warn("duplicate_edge", f"{n} edges for {key[2]} between the same nodes.", str(key))

        orphans = [e for e in entities if e.status == "active" and degree[e.id] == 0]
        if orphans:
            report._warn("orphan_nodes", f"{len(orphans)} active entities have no relationships.",
                         ", ".join(e.canonical_name for e in orphans[:10]))

        report.counts = {"entities": len(active_ids), "relationships": sum(1 for r in relationships if r.status == "active"),
                         "orphans": len(orphans)}
        return report
