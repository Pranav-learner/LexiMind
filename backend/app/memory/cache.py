"""Memory Cache (Step 14) — avoid repeated traversals of the same neighborhood.

A small process-wide LRU keyed by (workspace, sorted seed ids, hops, strategy, rel-filter). Traversal is
the expensive step; caching the `Neighborhood` makes repeated/related queries cheap. The cache is
invalidated per-workspace by the synchronizer whenever the graph changes (Step 10), keeping memory
eventually consistent. Keep it bounded so memory usage stays flat on large workspaces.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional, Tuple

from app.memory.interfaces import Neighborhood


class NeighborhoodCache:
    def __init__(self, capacity: int = 256):
        self._store: "OrderedDict[Tuple, Neighborhood]" = OrderedDict()
        self.capacity = capacity
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(workspace_id: str, seeds: List[str], hops: int, strategy: str,
             rel_types: Optional[List[str]]) -> Tuple:
        return (workspace_id, tuple(sorted(seeds)), hops, strategy,
                tuple(sorted(rel_types)) if rel_types else None)

    def get(self, workspace_id, seeds, hops, strategy, rel_types) -> Optional[Neighborhood]:
        key = self._key(workspace_id, seeds, hops, strategy, rel_types)
        nb = self._store.get(key)
        if nb is not None:
            self._store.move_to_end(key); self.hits += 1
        else:
            self.misses += 1
        return nb

    def put(self, workspace_id, seeds, hops, strategy, rel_types, neighborhood: Neighborhood) -> None:
        key = self._key(workspace_id, seeds, hops, strategy, rel_types)
        self._store[key] = neighborhood
        self._store.move_to_end(key)
        while len(self._store) > self.capacity:
            self._store.popitem(last=False)

    def invalidate_workspace(self, workspace_id: str) -> int:
        drop = [k for k in self._store if k[0] == workspace_id]
        for k in drop:
            del self._store[k]
        return len(drop)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"size": len(self._store), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0}


# process-wide cache (cheap; invalidated on graph mutation)
NEIGHBORHOOD_CACHE = NeighborhoodCache()
