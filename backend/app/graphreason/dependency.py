"""Dependency & Root-Cause Analysis (Step 7) — directed reasoning over dependency edges.

A dependency chain follows the DIRECTED dependency relations (`depends_on`, `uses`, `part_of`,
`prerequisite`, `extends`, `implements`) from an entity outward. Terminal nodes (no further outgoing
dependency) are the ROOT CAUSES / foundational dependencies — the answer to "what does X ultimately rest
on?" / "what caused this?". Confidence multiplies along the chain. Cycle-protected + depth-limited.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.graphreason.interfaces import DependencyChain

DEPENDENCY_RELS = ("depends_on", "uses", "part_of", "prerequisite", "extends", "implements")


class DependencyAnalyzer:
    name = "dependency-v1"

    def analyze(self, adjacency_directed, entities_by_id, root_id: str, *, max_depth: int = 5,
                max_chains: int = 20) -> Tuple[List[DependencyChain], List[Dict[str, Any]]]:
        root = entities_by_id.get(root_id)
        if root is None:
            return [], []
        chains: List[DependencyChain] = []
        root_causes: Dict[str, Dict[str, Any]] = {}

        def name(nid):
            e = entities_by_id.get(nid)
            return e.canonical_name if e else nid

        def dfs(node, names, rels, conf, visited):
            outgoing = [(n, e) for n, e in adjacency_directed.get(node, [])
                        if e.rel_type in DEPENDENCY_RELS and n not in visited]
            terminal = not outgoing or len(names) - 1 >= max_depth
            if len(names) > 1 and (terminal or len(chains) < max_chains):
                is_rc = terminal
                chains.append(DependencyChain(root=root_id, root_name=root.canonical_name, chain=list(names),
                                              rel_types=list(rels), depth=len(names) - 1,
                                              confidence=round(conf, 6), is_root_cause=is_rc))
                if is_rc:
                    leaf = names[-1]
                    rc = root_causes.get(leaf)
                    if rc is None or conf > rc["confidence"]:
                        root_causes[leaf] = {"entity": leaf, "confidence": round(conf, 4),
                                             "depth": len(names) - 1, "via": names[1:-1]}
            if terminal or len(chains) >= max_chains:
                return
            for n, e in outgoing:
                dfs(n, names + [name(n)], rels + [e.rel_type], conf * max(0.1, e.confidence),
                    visited | {n})

        dfs(root_id, [root.canonical_name], [], 1.0, {root_id})
        chains.sort(key=lambda c: (c.depth, c.confidence), reverse=True)
        ranked_rc = sorted(root_causes.values(), key=lambda r: (r["depth"], r["confidence"]), reverse=True)
        return chains[:max_chains], ranked_rc
