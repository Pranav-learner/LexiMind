"""Multi-Hop Graph Reasoning (Step 3) — enumerate reasoning PATHS (not just neighborhoods).

Builds an adjacency from the workspace's active edges (reusing the Module-1 graph store), then walks
DFS from the seeds up to `hops` edges to enumerate reasoning paths — with cycle detection (no repeated
node in a path), depth limits, weighted pruning (heavier edges first + a min-weight floor), a path cap,
and workspace isolation. Supports directed traversal (for dependency reasoning: follow source→target)
and undirected (for general semantic paths). A path is the semantic chain
`A —uses→ B —depends_on→ C` the reasoner explains + infers over.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.graphreason.interfaces import PathEdge, ReasoningPath

DECAY = 0.9
MIN_EDGE_WEIGHT = 0.05


def build_adjacency(edges, entities_by_id, *, directed: bool = False) -> Dict[str, List[Tuple[str, Any]]]:
    """node -> [(neighbor_id, edge)], heaviest edges first. Directed follows source→target only."""
    adj: Dict[str, List[Tuple[str, Any]]] = {}
    for e in edges:
        if e.source_id not in entities_by_id or e.target_id not in entities_by_id:
            continue
        adj.setdefault(e.source_id, []).append((e.target_id, e))
        if not directed:
            adj.setdefault(e.target_id, []).append((e.source_id, e))
    for node in adj:
        adj[node].sort(key=lambda t: t[1].weight, reverse=True)
    return adj


class PathReasoner:
    name = "dfs-paths-v1"

    def find_paths(self, adjacency, entities_by_id, seeds: List[str], *, hops: int = 3,
                   directed: bool = False, max_paths: int = 40, targets: Optional[List[str]] = None) -> List[ReasoningPath]:
        target_set = set(targets) if targets else None
        paths: List[ReasoningPath] = []

        def name(nid: str) -> str:
            e = entities_by_id.get(nid)
            return e.canonical_name if e else nid

        def dfs(node: str, visited_nodes: List[str], edges_acc: List[PathEdge]) -> None:
            if len(paths) >= max_paths:
                return
            if edges_acc and (target_set is None or node in target_set):
                conf = 1.0
                for pe in edges_acc:
                    conf *= max(0.05, pe.confidence)
                conf *= DECAY ** (len(edges_acc) - 1)
                weight = min((pe.weight for pe in edges_acc), default=0.0)
                paths.append(ReasoningPath(node_ids=list(visited_nodes),
                                           node_names=[name(n) for n in visited_nodes],
                                           edges=list(edges_acc), path_confidence=round(conf, 6),
                                           weight=round(weight, 4)))
            if len(edges_acc) >= hops:
                return
            for neighbor, edge in adjacency.get(node, []):
                if neighbor in visited_nodes:              # cycle protection
                    continue
                if edge.weight < MIN_EDGE_WEIGHT:
                    continue
                # orient the edge along the direction of travel
                src, tgt = (node, neighbor)
                pe = PathEdge(rel_id=edge.id, rel_type=edge.rel_type, source_id=src, target_id=tgt,
                              source_name=name(src), target_name=name(tgt), weight=edge.weight,
                              confidence=edge.confidence, evidence=list(edge.evidence or [])[:1])
                dfs(neighbor, visited_nodes + [neighbor], edges_acc + [pe])
                if len(paths) >= max_paths:
                    return

        for s in seeds:
            if s in entities_by_id:
                dfs(s, [s], [])
        # richest first: longer, higher-confidence paths lead the explanation
        paths.sort(key=lambda p: (p.length, p.path_confidence), reverse=True)
        return paths[:max_paths]
