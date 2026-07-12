"""Evaluation cache (Step 13) — avoid recomputing unchanged evaluations.

Content-addressed by (pipeline, pipeline_version, dataset_version, item_id, question) so re-running a
benchmark whose pipeline + dataset are unchanged returns cached per-item outputs instantly (incremental
evaluation). Bounded LRU. A pipeline/dataset version bump invalidates automatically (it changes the key).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional, Tuple


class EvaluationCache:
    def __init__(self, capacity: int = 2048):
        self._store: "OrderedDict[Tuple, object]" = OrderedDict()
        self.capacity = capacity
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(pipeline: str, version: str, dataset_version: int, item_id: str, question: str) -> Tuple:
        return (pipeline, version, dataset_version, item_id, hash(question))

    def get(self, pipeline, version, dataset_version, item_id, question):
        k = self._key(pipeline, version, dataset_version, item_id, question)
        v = self._store.get(k)
        if v is not None:
            self._store.move_to_end(k); self.hits += 1
        else:
            self.misses += 1
        return v

    def put(self, pipeline, version, dataset_version, item_id, question, value) -> None:
        k = self._key(pipeline, version, dataset_version, item_id, question)
        self._store[k] = value
        self._store.move_to_end(k)
        while len(self._store) > self.capacity:
            self._store.popitem(last=False)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"size": len(self._store), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0}


EVAL_CACHE = EvaluationCache()
