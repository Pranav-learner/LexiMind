"""Cache Intelligence (Step 7).

Two roles: (1) an ANSWER cache — a workspace-scoped, content-addressed store so a repeated query serves the
cached answer (the single biggest saving); (2) a cache OBSERVATORY that aggregates the stats of the caches
already living in other modules (semantic-memory neighborhood cache, graph-reasoning cache, evaluation
cache) into one view, with adaptive-eviction config. It does NOT replace those caches — it reports on them
and adds the answer layer the pipeline lacked.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class AnswerCache:
    """Bounded content-addressed answer cache (LRU + TTL). Adaptive eviction = LRU by capacity."""

    def __init__(self, capacity: int = 512, ttl_seconds: float = 3600.0):
        self.capacity = capacity
        self.ttl = ttl_seconds
        self._store: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(workspace_id: str, query: str) -> str:
        norm = " ".join((query or "").lower().split())
        return hashlib.sha256(f"{workspace_id}::{norm}".encode()).hexdigest()[:32]

    def get(self, workspace_id: str, query: str, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        now = now if now is not None else time.monotonic()
        k = self.key(workspace_id, query)
        entry = self._store.get(k)
        if entry is None:
            self.misses += 1
            return None
        ts, value = entry
        if now - ts > self.ttl:                          # expired
            self._store.pop(k, None)
            self.misses += 1
            return None
        self._store.move_to_end(k)
        self.hits += 1
        return value

    def put(self, workspace_id: str, query: str, value: Dict[str, Any], *, now: Optional[float] = None) -> None:
        now = now if now is not None else time.monotonic()
        k = self.key(workspace_id, query)
        self._store[k] = (now, value)
        self._store.move_to_end(k)
        while len(self._store) > self.capacity:          # evict LRU
            self._store.popitem(last=False)

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {"entries": len(self._store), "capacity": self.capacity, "hits": self.hits,
                "misses": self.misses, "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "ttl_seconds": self.ttl}


# a single shared answer cache (module-level, like the other module caches)
ANSWER_CACHE = AnswerCache()


class CacheIntelligence:
    """Aggregates all known cache layers into one adaptive report."""

    def __init__(self, answer_cache: AnswerCache | None = None):
        self.answer_cache = answer_cache or ANSWER_CACHE

    def report(self) -> Dict[str, Any]:
        layers: Dict[str, Any] = {"answer": self.answer_cache.stats()}
        # reuse the caches other modules already maintain (no duplication)
        for label, dotted in (("graph_neighborhood", "app.memory.cache"),
                              ("graph_reasoning", "app.graphreason.confidence"),
                              ("evaluation", "app.evaluation.cache")):
            layers[label] = self._probe(dotted)
        # overall adaptive recommendation
        ans = layers["answer"]
        recommendation = ("healthy" if ans["hit_rate"] >= 0.3 or ans["entries"] < 20
                          else "low hit-rate — consider longer TTL or query normalization")
        return {"layers": layers, "recommendation": recommendation}

    @staticmethod
    def _probe(dotted: str) -> Dict[str, Any]:
        """Best-effort read of another module's cache stats — never raises."""
        try:
            import importlib
            mod = importlib.import_module(dotted)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if hasattr(obj, "stats") and callable(getattr(obj, "stats")):
                    try:
                        s = obj.stats()
                        if isinstance(s, dict):
                            return {"available": True, **{k: s[k] for k in list(s)[:6]}}
                    except Exception:
                        continue
                if isinstance(obj, dict) and attr.isupper() and "CACHE" in attr:
                    return {"available": True, "entries": len(obj)}
            return {"available": False}
        except Exception:
            return {"available": False}
