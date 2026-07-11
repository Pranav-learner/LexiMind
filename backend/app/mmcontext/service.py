"""Multimodal Context Engineering orchestrator (the evolution of Phase-2 ContextBuilderService).

CONSUMES Module-3 retrieval results (never duplicates retrieval) and runs the modular pipeline:
retrieve → cross-modal dedup → cross-modal ranking → adaptive token budgeting + compression →
adaptive assembly → multimodal prompt build → citation collection → metrics/log. Phase-2
(`app/context/`) is untouched; this is a parallel, modality-aware engine reusing Phase-2's tokenizer.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.context.tokenizer import heuristic_token_count
from app.mmcontext import assembly as assemble_mod
from app.mmcontext import budget as budget_mod
from app.mmcontext import citations as citations_mod
from app.mmcontext import compression as compress_mod
from app.mmcontext import dedup as dedup_mod
from app.mmcontext import prompt as prompt_mod
from app.mmcontext import ranking as ranking_mod
from app.mmcontext.models import ContextBuildLog
from app.mmcontext.repository import ContextRepository
from app.mmcontext.schemas import ContextBuildRequest, MMEvidence
from app.mmretrieval.intent import analyze_intent
from app.mmretrieval.repository import RetrievalRepository
from app.mmretrieval.schemas import SearchRequest
from app.mmretrieval.service import MultimodalRetrievalService


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MultimodalContextService:
    def __init__(self, db, *, text_retriever=None):
        self.db = db
        self.repo = ContextRepository(db)
        self.text_retriever = text_retriever

    def _default_budget(self, override: int | None) -> int:
        if override:
            return override
        from app.core.config import settings
        return max(512, settings.context_window - settings.system_prompt_reserve - settings.response_reserve)

    # ------------------------------------------------------------------ the pipeline
    def build(self, owner_id: str, workspace_id: str, req: ContextBuildRequest) -> Dict[str, Any]:
        started = time.perf_counter()
        stage_ms: Dict[str, float] = {}

        # 1) Consume Module-3 retrieval (rerank + explain on so we inherit all signals).
        t = time.perf_counter()
        search = MultimodalRetrievalService(RetrievalRepository(self.db), text_retriever=self.text_retriever).search(
            owner_id, workspace_id, SearchRequest(
                query=req.query, modalities=req.modalities, document_id=req.document_id,
                top_k=req.top_k, rerank=True, explain=True))
        stage_ms["retrieval"] = round((time.perf_counter() - t) * 1000, 3)

        intent = analyze_intent(req.query)
        weights = {k: float(v) for k, v in search["weights"].items()}
        primary = search["primary"]
        evidence = [self._to_evidence(r) for r in search["results"]]
        retrieved = len(evidence)

        # 2) Cross-modal duplicate detection.
        t = time.perf_counter()
        deduped, removed = dedup_mod.deduplicate(evidence) if req.dedup else (evidence, 0)
        stage_ms["dedup"] = round((time.perf_counter() - t) * 1000, 3)

        # 3) Cross-modal evidence ranking.
        t = time.perf_counter()
        ranked = ranking_mod.rank(deduped, weights)
        stage_ms["rank"] = round((time.perf_counter() - t) * 1000, 3)

        # 4) Adaptive token budgeting + compression.
        t = time.perf_counter()
        total_budget = self._default_budget(req.token_budget)
        original_tokens = sum(heuristic_token_count(e.content) for e in ranked)
        compress_fn = (lambda ev, limit: compress_mod.compress(ev.content, ev.modality, limit, intent.keywords, ev.metadata)) if req.compress else None
        included, dropped, used = budget_mod.manage(ranked, weights, total_budget, compress=req.compress, compress_fn=compress_fn)
        stage_ms["budget"] = round((time.perf_counter() - t) * 1000, 3)

        # 5) Adaptive assembly + 6) prompt build + 7) citations.
        t = time.perf_counter()
        blocks = assemble_mod.assemble(included, weights, primary)
        stage_ms["assemble"] = round((time.perf_counter() - t) * 1000, 3)
        t = time.perf_counter()
        full_prompt, context_text, _cindex = prompt_mod.build(req.query, blocks)
        citations = citations_mod.collect(blocks)
        stage_ms["prompt"] = round((time.perf_counter() - t) * 1000, 3)

        context_tokens = sum(e.token_cost for e in included)
        prompt_tokens = heuristic_token_count(full_prompt)
        total_ms = round((time.perf_counter() - started) * 1000, 3)
        dup_reduction = round(removed / retrieved, 4) if retrieved else 0.0
        comp_ratio = round(context_tokens / original_tokens, 4) if original_tokens else 1.0

        # Observability log (single cheap insert).
        self.repo.log_build(ContextBuildLog(
            workspace_id=workspace_id, owner_id=owner_id, query=req.query[:2000], primary_intent=primary,
            modalities=sorted(weights.keys()), retrieved=retrieved, after_dedup=len(deduped),
            included=len(included), context_tokens=context_tokens, prompt_tokens=prompt_tokens,
            duplicate_reduction=dup_reduction, compression_ratio=comp_ratio, total_ms=total_ms, stage_ms=stage_ms))

        return {
            "query": req.query, "primary_intent": primary, "modalities": sorted(weights.keys()),
            "weights": {k: round(v, 3) for k, v in weights.items()},
            "blocks": [self._block_out(b, req.explain) for b in blocks],
            "citations": [self._citation_out(c) for c in citations],
            "budget": [{"modality": m, "allocated": budget_mod.allocate(weights, sorted({e.modality for e in ranked}), total_budget).get(m, 0),
                        "used": used.get(m, 0)} for m in sorted(used.keys())],
            "metrics": {
                "retrieved": retrieved, "after_dedup": len(deduped), "included": len(included),
                "dropped": len(dropped), "context_tokens": context_tokens, "prompt_tokens": prompt_tokens,
                "duplicate_reduction": dup_reduction, "compression_ratio": comp_ratio,
                "total_ms": total_ms, "stage_ms": stage_ms,
            },
            "dropped": dropped,
            "prompt": full_prompt if req.developer else None,
            "context": context_text if req.developer else None,
        }

    # ------------------------------------------------------------------ conversions
    def _to_evidence(self, r: Dict[str, Any]) -> MMEvidence:
        exp = r.get("explanation") or {}
        meta = r.get("metadata") or {}
        conf = meta.get("confidence") if r["modality"] in ("image", "diagram", "table") else None
        return MMEvidence(
            key=r["key"], modality=r["modality"], source_type=r["source_type"], content=r.get("content", ""),
            title=r.get("title", ""), document_id=r.get("document_id"), chunk_id=r.get("chunk_id"),
            asset_id=r.get("asset_id"), page_number=r.get("page_number"),
            base_score=float(r.get("confidence", 0.0)), retrieval_score=float(exp.get("normalized_score", 0.0)),
            rerank_score=float(exp.get("reranker_score") or 0.0), vision_confidence=conf,
            contributing_modalities=list(exp.get("contributing_modalities", []) or []), metadata=meta)

    def _block_out(self, b, explain: bool) -> Dict[str, Any]:
        return {"modality": b.modality, "header": b.header, "order": b.order, "token_cost": b.token_cost,
                "items": [self._evidence_out(e, explain) for e in b.items]}

    def _evidence_out(self, e: MMEvidence, explain: bool) -> Dict[str, Any]:
        out = {
            "key": e.key, "modality": e.modality, "source_type": e.source_type, "title": e.title,
            "content": e.content, "document_id": e.document_id, "page_number": e.page_number,
            "evidence_score": e.evidence_score, "token_cost": e.token_cost, "compressed": e.compressed,
            "rank": e.rank, "selection_reason": e.selection_reason,
            "contributing_modalities": e.contributing_modalities, "merged_from": e.merged_from,
        }
        if explain:
            out["ranking_contributions"] = e.ranking_contributions
        return out

    @staticmethod
    def _citation_out(c) -> Dict[str, Any]:
        return {"modality": c.modality, "document_id": c.document_id, "chunk_id": c.chunk_id,
                "asset_id": c.asset_id, "page_number": c.page_number, "source_type": c.source_type, "text": c.text}

    # ------------------------------------------------------------------ observability
    def observability(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.observability(workspace_id)
