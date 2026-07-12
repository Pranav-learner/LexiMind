"""Temporal retrieval orchestration — the Temporal Retriever Orchestrator (Steps 2–9, 14).

Pipeline: ensure temporal intelligence is derived → temporal query analysis → run the activated
temporal retrievers → normalize each modality → temporal fusion → temporal rerank → timeline-aware
context assembly → adaptive timestamp-preserving prompt → temporal citations → log. Reuses the
mmretrieval normalizer (unchanged) and the Phase-2/4 tokenizer + compressor (unchanged).

Retrievers are independent and PARALLELIZABLE; they run sequentially on the request-scoped DB session
(SQLite Session isn't thread-safe) — structured so a session-per-retriever executor can parallelize
later without touching fusion/rerank. Per-stage latency is always measured (observability).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.mmretrieval import normalize as norm
from app.tretrieval import fusion as fusion_mod
from app.tretrieval import intent as intent_mod
from app.tretrieval.citations import build_citations
from app.tretrieval.context import build_context
from app.tretrieval.errors import TemporalValidationError
from app.tretrieval.models import TemporalSearchLog
from app.tretrieval.prompt import build_prompt
from app.tretrieval.rerank import LexicalTemporalReranker, no_rerank
from app.tretrieval.repository import TemporalRepository
from app.tretrieval.retrievers import TEMPORAL_RETRIEVERS, TemporalContext
from app.tretrieval.schemas import TEMPORAL_MODALITIES, TemporalHit, TemporalSearchRequest


def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{(s % 3600) // 60:02d}:{s % 60:02d}"


class TemporalRetrievalService:
    def __init__(self, repo: TemporalRepository, *, reranker=None):
        self.repo = repo
        self.db = repo.db
        self.reranker = reranker or LexicalTemporalReranker()

    # ------------------------------------------------------------------ derivation guard
    def _ensure_intelligence(self, owner_id: str, workspace_id: str, document_id: Optional[str]) -> None:
        """Make sure chapters/topics/events exist for the recordings we're about to search (cheap,
        count-guarded). Keeps chapter/topic/event retrievers non-empty without touching Module-1."""
        from app.tintel.repository import TemporalIntelRepository
        from app.tintel.service import TemporalIntelService
        tintel = TemporalIntelService(TemporalIntelRepository(self.db))
        for doc_id in self.repo.processed_media_docs(workspace_id, owner_id, document_id):
            try:
                tintel.ensure_derived(doc_id, owner_id, workspace_id)
            except Exception:
                continue

    # ------------------------------------------------------------------ search
    def search(self, owner_id: str, workspace_id: str, req: TemporalSearchRequest) -> Dict[str, Any]:
        started = time.perf_counter()
        self._ensure_intelligence(owner_id, workspace_id, req.document_id)

        t_an = time.perf_counter()
        intent = intent_mod.analyze(req.query)
        analysis_ms = (time.perf_counter() - t_an) * 1000

        if req.modalities:
            requested = [m for m in req.modalities if m in TEMPORAL_MODALITIES]
            if not requested:
                raise TemporalValidationError(
                    f"Unknown temporal modalities. Supported: {', '.join(TEMPORAL_MODALITIES)}.")
            modalities = set(requested)
            weights = {m: intent.weights.get(m, intent_mod.BASE_WEIGHTS.get(m, 0.5)) for m in modalities}
        else:
            modalities = set(intent.modalities)
            weights = dict(intent.weights)

        ctx = TemporalContext(db=self.db, workspace_id=workspace_id, owner_id=owner_id, query=req.query,
                              keywords=intent.keywords, document_id=req.document_id,
                              time_filter=intent.time_filter, repo=self.repo)

        by_modality: Dict[str, List[TemporalHit]] = {}
        retriever_stats: List[Dict[str, Any]] = []
        for modality in modalities:
            retriever = TEMPORAL_RETRIEVERS.get(modality)
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

        t_fuse = time.perf_counter()
        fused = fusion_mod.fuse(by_modality, weights, strategy=req.fusion)
        fusion_ms = (time.perf_counter() - t_fuse) * 1000

        t_rr = time.perf_counter()
        if req.rerank:
            ranked = self.reranker.rerank(req.query, intent.keywords, fused, primary=intent.primary)
        else:
            ranked = no_rerank(fused)
            for i, h in enumerate(ranked, start=1):
                h.final_rank = i
        rerank_ms = (time.perf_counter() - t_rr) * 1000

        top = ranked[:req.top_k]

        # Timeline-aware context + adaptive prompt + temporal citations.
        context_ms = prompt_ms = 0.0
        prompt_text = None
        context_blocks = None
        citations: List[Dict[str, Any]] = []
        if req.build_context and top:
            t_ctx = time.perf_counter()
            blocks, _stats = build_context(top, intent.keywords)
            context_ms = (time.perf_counter() - t_ctx) * 1000
            t_pr = time.perf_counter()
            _system, prompt_text, _cit = build_prompt(req.query, intent.query_type, blocks)
            prompt_ms = (time.perf_counter() - t_pr) * 1000
            citations = build_citations(blocks)
            context_blocks = [{
                "citation_index": b.citation_index, "modality": b.modality, "document_id": b.document_id,
                "start_ms": b.start_ms, "end_ms": b.end_ms, "timespan": b.metadata.get("timespan"),
                "speaker_label": b.speaker_label, "tokens": b.tokens, "content": b.content,
            } for b in blocks]

        total_ms = (time.perf_counter() - started) * 1000
        self.repo.log_search(TemporalSearchLog(
            workspace_id=workspace_id, owner_id=owner_id, document_id=req.document_id,
            query=req.query[:2000], intents=sorted(modalities), primary=intent.primary,
            result_count=len(top), total_ms=round(total_ms, 3), analysis_ms=round(analysis_ms, 3),
            fusion_ms=round(fusion_ms, 3), rerank_ms=round(rerank_ms, 3), context_ms=round(context_ms, 3),
            prompt_ms=round(prompt_ms, 3),
            retriever_stats={s["modality"]: {"ms": s["latency_ms"], "count": s["count"]} for s in retriever_stats}))

        return {
            "query": req.query, "intents": sorted(modalities), "detected": intent.detected,
            "primary": intent.primary, "weights": {k: round(v, 3) for k, v in weights.items()},
            "time_filter": ({"start_ms": intent.time_filter.start_ms, "end_ms": intent.time_filter.end_ms,
                             "anchor_ms": intent.time_filter.anchor_ms} if intent.time_filter else None),
            "total": len(top), "total_ms": round(total_ms, 3), "analysis_ms": round(analysis_ms, 3),
            "fusion_ms": round(fusion_ms, 3), "rerank_ms": round(rerank_ms, 3),
            "context_ms": round(context_ms, 3), "prompt_ms": round(prompt_ms, 3),
            "retriever_stats": retriever_stats,
            "results": [self._result_out(h, req.explain) for h in top],
            "citations": citations, "prompt": prompt_text, "context_blocks": context_blocks,
        }

    def _result_out(self, h: TemporalHit, explain: bool) -> Dict[str, Any]:
        out = {
            "key": h.key, "modality": h.modality, "source_type": h.source_type,
            "document_id": h.document_id, "title": h.title, "content": h.content,
            "start_ms": h.start_ms, "end_ms": h.end_ms, "timespan": f"{_fmt(h.start_ms)}–{_fmt(h.end_ms)}",
            "speaker_id": h.speaker_id, "speaker_label": h.speaker_label, "scene_id": h.scene_id,
            "chapter_id": h.chapter_id, "frame_id": h.frame_id, "confidence": h.confidence,
            "final_rank": h.final_rank, "metadata": h.metadata,
        }
        if explain:
            out["explanation"] = {
                "retriever": h.modality, "raw_score": round(h.raw_score, 6),
                "normalized_score": h.normalized_score, "rank_in_modality": h.rank_in_modality,
                "proximity_bonus": h.proximity_bonus, "fusion_score": round(h.fusion_score, 6),
                "fusion_contributions": h.fusion_contributions, "reranker_score": h.reranker_score,
                "contributing_modalities": h.contributing_modalities, "final_rank": h.final_rank,
            }
        return out

    # ------------------------------------------------------------------ prompt preview / explain
    def prompt_preview(self, owner_id: str, workspace_id: str, req: TemporalSearchRequest) -> Dict[str, Any]:
        req = req.model_copy(update={"build_context": True})
        result = self.search(owner_id, workspace_id, req)
        intent = intent_mod.analyze(req.query)
        from app.context.tokenizer import heuristic_token_count
        prompt = result.get("prompt") or ""
        from app.tretrieval.prompt import _SYSTEM
        return {"query": req.query, "query_type": intent.query_type, "prompt": prompt,
                "system_prompt": _SYSTEM, "citations": result.get("citations", []),
                "token_estimate": heuristic_token_count(prompt)}

    def explain(self, owner_id: str, workspace_id: str, req: TemporalSearchRequest) -> Dict[str, Any]:
        result = self.search(owner_id, workspace_id, req.model_copy(update={"explain": True, "build_context": False}))
        intent = intent_mod.analyze(req.query)
        return {"query": req.query,
                "analysis": {"keywords": intent.keywords, "detected": intent.detected,
                             "primary": intent.primary, "query_type": intent.query_type,
                             "weights": {k: round(v, 3) for k, v in intent.weights.items()},
                             "time_filter": result.get("time_filter")},
                "results": result["results"]}

    # ------------------------------------------------------------------ stats / health
    def stats(self, workspace_id: str) -> Dict[str, Any]:
        s = self.repo.stats(workspace_id)
        s["indexed"] = self.repo.indexed_counts(workspace_id)
        return s

    def health(self, workspace_id: str) -> Dict[str, Any]:
        return {"status": "ok", "retrievers": list(TEMPORAL_RETRIEVERS.keys()),
                "indexed": self.repo.indexed_counts(workspace_id)}
