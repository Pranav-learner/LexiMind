"""Multimodal retrieval orchestration — the Retriever Orchestrator.

Pipeline: intent analysis → run the activated retrievers → normalize each modality's scores → fuse →
cross-modal rerank → explain → log. Reuses Phase-1 hybrid retrieval (untouched) for the text
modality when injected in production; the DB-backed retrievers cover OCR/image/diagram/table/metadata.

Retrievers are independent and PARALLELIZABLE; here they run sequentially on the request-scoped DB
session (SQLite `Session` is not thread-safe) — the code is structured so a session-per-retriever
executor can parallelize later without touching fusion/rerank. Per-retriever latency is measured
either way.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.mmretrieval import fusion as fusion_mod
from app.mmretrieval import normalize as norm
from app.mmretrieval.errors import RetrievalValidationError
from app.mmretrieval.intent import BASE_WEIGHTS, analyze_intent
from app.mmretrieval.models import RetrievalLog
from app.mmretrieval.rerank import LexicalCrossModalReranker, no_rerank
from app.mmretrieval.repository import RetrievalRepository
from app.mmretrieval.retrievers import DB_RETRIEVERS, LexicalTextRetriever, RetrievalContext
from app.mmretrieval.schemas import MODALITIES, RetrievalHit, SearchRequest


class MultimodalRetrievalService:
    def __init__(self, repo: RetrievalRepository, *, text_retriever=None, reranker=None):
        self.repo = repo
        self.db = repo.db
        self.text_retriever = text_retriever or LexicalTextRetriever()
        self.reranker = reranker or LexicalCrossModalReranker()

    # ------------------------------------------------------------------ search
    def search(self, owner_id: str, workspace_id: str, req: SearchRequest) -> Dict[str, Any]:
        started = time.perf_counter()
        intent = analyze_intent(req.query)

        # Modality selection: explicit override, else intent-detected.
        if req.modalities:
            requested = [m for m in req.modalities if m in MODALITIES]
            if not requested:
                raise RetrievalValidationError(f"Unknown modalities. Supported: {', '.join(MODALITIES)}.")
            modalities = set(requested)
            weights = {m: intent.weights.get(m, BASE_WEIGHTS.get(m, 0.5)) for m in modalities}
        else:
            modalities = set(intent.modalities)
            weights = dict(intent.weights)

        ctx = RetrievalContext(db=self.db, workspace_id=workspace_id, owner_id=owner_id,
                               query=req.query, keywords=intent.keywords, document_id=req.document_id,
                               repo=self.repo)

        # Run each activated retriever, normalize its scores in place.
        by_modality: Dict[str, List[RetrievalHit]] = {}
        retriever_stats: List[Dict[str, Any]] = []
        for modality in modalities:
            retriever = self.text_retriever if modality == "text" else DB_RETRIEVERS.get(modality)
            if retriever is None:
                continue
            t0 = time.perf_counter()
            try:
                hits = retriever.retrieve(ctx, req.per_retriever_k)
            except Exception:
                hits = []
            dt = (time.perf_counter() - t0) * 1000
            scores = norm.normalize([h.raw_score for h in hits], req.normalize)
            for h, s in zip(hits, scores):
                h.normalized_score = round(s, 6)
            by_modality[modality] = hits
            retriever_stats.append({"modality": modality, "count": len(hits), "latency_ms": round(dt, 3)})

        # Fusion.
        t_fuse = time.perf_counter()
        fused = fusion_mod.fuse(by_modality, weights, strategy=req.fusion)
        fusion_ms = (time.perf_counter() - t_fuse) * 1000

        # Cross-modal rerank (or fusion-only confidence).
        t_rr = time.perf_counter()
        if req.rerank:
            ranked = self.reranker.rerank(req.query, intent.keywords, fused, primary=intent.primary)
        else:
            ranked = no_rerank(fused)
            for i, h in enumerate(ranked, start=1):
                h.final_rank = i
        rerank_ms = (time.perf_counter() - t_rr) * 1000

        top = ranked[:req.top_k]
        total_ms = (time.perf_counter() - started) * 1000

        # Log the search (single cheap insert; powers stats + Phase-9 dashboards).
        self.repo.log_search(RetrievalLog(
            workspace_id=workspace_id, owner_id=owner_id, query=req.query[:2000],
            intents=sorted(modalities), result_count=len(top), total_ms=round(total_ms, 3),
            retriever_stats={s["modality"]: {"ms": s["latency_ms"], "count": s["count"]} for s in retriever_stats},
            fusion_ms=round(fusion_ms, 3), rerank_ms=round(rerank_ms, 3)))

        return {
            "query": req.query, "intents": sorted(modalities), "detected": intent.detected,
            "primary": intent.primary, "weights": {k: round(v, 3) for k, v in weights.items()},
            "total": len(top), "total_ms": round(total_ms, 3), "fusion_ms": round(fusion_ms, 3),
            "rerank_ms": round(rerank_ms, 3), "retriever_stats": retriever_stats,
            "results": [self._result_out(h, req.explain) for h in top],
        }

    def _result_out(self, h: RetrievalHit, explain: bool) -> Dict[str, Any]:
        out = {
            "key": h.key, "modality": h.modality, "source_type": h.source_type,
            "document_id": h.document_id, "chunk_id": h.chunk_id, "asset_id": h.asset_id,
            "page_number": h.page_number, "title": h.title, "content": h.content,
            "confidence": h.confidence, "final_rank": h.final_rank, "metadata": h.metadata,
        }
        if explain:
            out["explanation"] = {
                "retriever": h.modality, "source_type": h.source_type,
                "raw_score": round(h.raw_score, 6), "normalized_score": h.normalized_score,
                "rank_in_modality": h.rank_in_modality, "fusion_score": round(h.fusion_score, 6),
                "fusion_contributions": h.fusion_contributions, "reranker_score": h.reranker_score,
                "contributing_modalities": h.contributing_modalities, "final_rank": h.final_rank,
            }
        return out

    # ------------------------------------------------------------------ context-engine seam (Step 14)
    @staticmethod
    def to_context_chunks(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map unified multimodal results to the chunk shape Phase-2 consumes — the INTERFACE the
        future multimodal Context Engineering will use. Does NOT change Phase-2 behaviour."""
        return [{
            "chunk_id": r.get("chunk_id") or r.get("asset_id") or r.get("key"),
            "document_id": r.get("document_id"), "page_number": r.get("page_number"),
            "text": r.get("content", ""), "score": r.get("confidence", 0.0),
            "modality": r.get("modality"), "source": r.get("source_type"),
        } for r in results]

    # ------------------------------------------------------------------ suggestions / stats / health
    def suggestions(self, workspace_id: str, owner_id: str, query: str) -> List[str]:
        q = (query or "").lower().strip()
        out: List[str] = []
        for d in self.repo.documents(workspace_id, owner_id, limit=50):
            if q and q in (d.display_name or "").lower():
                out.append(d.display_name)
        for a in self.repo.vision(workspace_id, limit=50):
            if q and a.caption and q in a.caption.lower():
                out.append(a.caption[:80])
        # De-dup, cap.
        seen, dedup = set(), []
        for s in out:
            if s not in seen:
                seen.add(s); dedup.append(s)
        return dedup[:8]

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        s = self.repo.stats(workspace_id)
        s["indexed"] = self.repo.indexed_counts(workspace_id)
        return s

    def health(self, workspace_id: str) -> Dict[str, Any]:
        return {
            "status": "ok",
            "retrievers": ["text", *DB_RETRIEVERS.keys()],
            "text_backend": type(self.text_retriever).__name__,
            "indexed": self.repo.indexed_counts(workspace_id),
            "embedding_queue": self.repo.embedding_queue(workspace_id),
        }
