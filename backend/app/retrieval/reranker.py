"""Cross-encoder reranking with BAAI/bge-reranker-base.

WHY rerank:
- Bi-encoder dense retrieval and BM25 score query and chunk *independently*. A cross-
  encoder scores the (query, chunk) PAIR jointly, so it models term interaction and is
  far more precise — at a cost too high to run over the whole corpus. The standard
  recipe is: cheap retrieval gets a candidate set (top ~30), the expensive cross-
  encoder reorders it, we keep the top ~5. This is the single highest-leverage
  precision win in the Phase-1 pipeline.

DESIGN:
- Lazy model load: the model (~1.1GB) is only loaded on first rerank, so importing the
  package (and running tests that don't need reranking) stays fast and offline-safe.
- Batching: all cache-miss (query, chunk) pairs go to the model in one predict() call.
- Caching: an explicit bounded LRU keyed on (query, chunk_id). On repeated/paginated
  queries the same chunk isn't re-scored.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional, Tuple

from app.retrieval.schemas import RetrievedChunk


class RerankerService:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", *, cache_size: int = 4096):
        self.model_name = model_name
        self.cache_size = cache_size
        self._model = None  # lazily loaded CrossEncoder
        self._cache: "OrderedDict[Tuple[str, str], float]" = OrderedDict()

    # --- model -------------------------------------------------------------
    def _load(self):
        if self._model is None:
            # Imported here, not at module top, so the heavy transformers import only
            # happens when reranking is actually used.
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    # --- cache -------------------------------------------------------------
    def _cache_get(self, key: Tuple[str, str]) -> Optional[float]:
        if key in self._cache:
            self._cache.move_to_end(key)  # mark recently used
            return self._cache[key]
        return None

    def _cache_put(self, key: Tuple[str, str], value: float) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)  # evict least-recently-used

    # --- rerank ------------------------------------------------------------
    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        *,
        top_k: Optional[int] = None,
        batch_size: int = 32,
    ) -> List[RetrievedChunk]:
        """Score every candidate against the query and return them re-sorted.

        Cache hits are served from the LRU; only cache-miss pairs are sent to the
        model, batched in a single predict() call.
        """
        if not candidates:
            return []

        scores: List[Optional[float]] = [None] * len(candidates)
        misses: List[int] = []

        for i, c in enumerate(candidates):
            cached = self._cache_get((query, c.chunk_id))
            if cached is None:
                misses.append(i)
            else:
                scores[i] = cached

        if misses:
            model = self._load()
            pairs = [(query, candidates[i].text) for i in misses]
            predicted = model.predict(pairs, batch_size=batch_size)
            for i, raw in zip(misses, predicted):
                value = float(raw)
                scores[i] = value
                self._cache_put((query, candidates[i].chunk_id), value)

        reranked = [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                text=c.text,
                metadata=c.metadata,
                score=float(s) if s is not None else 0.0,
                retriever="reranker",
            )
            for c, s in zip(candidates, scores)
        ]

        reranked.sort(key=lambda c: c.score, reverse=True)
        if top_k is not None:
            reranked = reranked[:top_k]
        for rank, c in enumerate(reranked, start=1):
            c.rank = rank
        return reranked
