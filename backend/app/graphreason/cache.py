"""Reasoning Cache (Step 14) — avoid repeated reasoning over identical subgraphs.

A bounded LRU keyed by (workspace, sorted seed ids, hops, directed). Multi-hop path enumeration is the
expensive step; caching the reasoning result makes repeated/related queries cheap. Invalidated per
workspace when the graph changes (shares the Module-2 synchronizer's invalidation intent).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional, Tuple


class ReasoningCache:
    def __init__(self, capacity: int = 128):
        self._store: "OrderedDict[Tuple, object]" = OrderedDict()
        self.capacity = capacity
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(workspace_id: str, seeds: List[str], hops: int, directed: bool) -> Tuple:
        return (workspace_id, tuple(sorted(seeds)), hops, directed)

    def get(self, workspace_id, seeds, hops, directed):
        key = self._key(workspace_id, seeds, hops, directed)
        v = self._store.get(key)
        if v is not None:
            self._store.move_to_end(key); self.hits += 1
        else:
            self.misses += 1
        return v

    def put(self, workspace_id, seeds, hops, directed, value) -> None:
        key = self._key(workspace_id, seeds, hops, directed)
        self._store[key] = value
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


REASONING_CACHE = ReasoningCache()
