"""Graph Traversal Engine (Step 5) — expand seeds into a semantic neighborhood.

Loads the workspace's active edges ONCE, builds an undirected adjacency (with edge weights), then walks
outward from the seeds up to `hops` using BFS or DFS. Features: N-hop limit, breadth/depth-first,
relationship-type filtering, weighted expansion (high-weight edges explored first when capping), a node
cap (`max_nodes`) for large-graph safety, cycle protection (visited set), and workspace isolation (the
repository is already workspace+owner scoped). Configurable per query.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

from app.memory.interfaces import Neighborhood


class TraversalEngine:
    def __init__(self, name: str = "bfs"):
        self.name = name

    def expand(self, repo, workspace_id: str, owner_id: str, seeds: List[str], *, hops: int = 2,
               strategy: str = "bfs", rel_types: Optional[List[str]] = None,
               max_nodes: int = 60) -> Neighborhood:
        nb = Neighborhood(seeds=list(seeds))
        if not seeds:
            return nb

        edges = repo.workspace_relationships(workspace_id, owner_id, limit=5000)
        if rel_types:
            allow = set(rel_types)
            edges = [e for e in edges if e.rel_type in allow]
        # adjacency: node -> [(neighbor, edge)], sorted so heavier edges are expanded first
        adj: Dict[str, List] = {}
        for e in edges:
            adj.setdefault(e.source_id, []).append((e.target_id, e))
            adj.setdefault(e.target_id, []).append((e.source_id, e))
        for node in adj:
            adj[node].sort(key=lambda t: t[1].weight, reverse=True)

        all_ids = set(seeds)
        for e in edges:
            all_ids.update((e.source_id, e.target_id))
        by_id = {en.id: en for en in repo.workspace_entities(workspace_id, owner_id) if en.id in all_ids}

        visited = set(seeds)
        for s in seeds:
            if s in by_id:
                nb.nodes[s] = by_id[s]; nb.hop[s] = 0

        # BFS = FIFO deque; DFS = LIFO stack (same visited/hop bookkeeping)
        frontier = deque((s, 0) for s in seeds if s in by_id)
        used_edges = set()
        while frontier:
            node, dist = frontier.popleft() if strategy == "bfs" else frontier.pop()
            if dist >= hops:
                continue
            for neighbor, edge in adj.get(node, []):
                if edge.id not in used_edges and neighbor in by_id:
                    nb.edges.append(edge); used_edges.add(edge.id)
                if neighbor in visited:
                    continue
                if len(nb.nodes) >= max_nodes:
                    nb.truncated = True
                    continue
                visited.add(neighbor)
                if neighbor in by_id:
                    nb.nodes[neighbor] = by_id[neighbor]
                    nb.hop[neighbor] = dist + 1
                    frontier.append((neighbor, dist + 1))
        return nb
