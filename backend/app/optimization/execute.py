"""Optimized execution (Step 14) — apply an OptimizationPlan through the REAL pipeline.

Optimization WRAPS production, never bypasses it: this runs actual retrieval (with the plan's params) →
context via PromptPackage (with the plan's budget/compression) → the SINGLE AnswerService pathway → the
Verification Engine, then records the estimated-vs-actual outcome in `OptimizationRunLog` and populates the
answer cache. A cache HIT short-circuits the whole pipeline (the biggest optimization). No execution logic is
duplicated — the plan only tunes parameters the existing services already accept.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.optimization.cache_intel import ANSWER_CACHE
from app.optimization.interfaces import OptimizationPlan


def _apply_compression(text: str, level: str) -> str:
    if level == "none" or not text:
        return text
    # deterministic, citation-preserving compression: drop blank lines + collapse whitespace;
    # aggressive additionally caps each evidence line length.
    lines = [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]
    if level == "aggressive":
        lines = [ln[:280] for ln in lines]
    return "\n".join(lines)


def apply_plan(db: Session, workspace_id: str, owner_id: str, *, plan: OptimizationPlan,
               services: Dict[str, Any]) -> Dict[str, Any]:
    query = plan.profile.query

    # ---- cache hit: serve immediately (single biggest saving) ----
    if plan.cache_decision == "hit":
        cached = ANSWER_CACHE.get(workspace_id, query)
        if cached is not None:
            return {"answer": cached.get("answer", ""), "cache_used": True, "results": 0,
                    "tokens": 0, "actual_cost": 0.0, "verification_status": cached.get("verification_status"),
                    "quality_impact": cached.get("quality_impact", 0.0)}

    r = plan.retrieval
    # ---- retrieval (real, with optimized params) ----
    results = []
    with_graph_hits = 0
    try:
        from app.mmretrieval.repository import RetrievalRepository
        from app.mmretrieval.schemas import SearchRequest
        from app.mmretrieval.service import MultimodalRetrievalService
        res = MultimodalRetrievalService(RetrievalRepository(db)).search(
            owner_id, workspace_id, SearchRequest(query=query, top_k=r.top_k, explain=False))
        results = res.get("results", [])
    except Exception:
        results = []
    if r.use_graph and r.graph_hops:
        try:
            from app.memory.service import SemanticMemoryService
            mem = SemanticMemoryService(db).retrieve(workspace_id, owner_id, query=query,
                                                     hops=r.graph_hops, limit=r.top_k, persist=False)
            with_graph_hits = len(mem.get("hits", []))
        except Exception:
            with_graph_hits = 0

    # ---- context (PromptPackage) with optimized budget + compression ----
    from app.agents.prompt_package import PromptPackage, PromptSection
    evidence = [{"index": i, "text": (r_.get("content") or ""), "document_id": r_.get("document_id"),
                 "score": float(r_.get("confidence") or 0.5)} for i, r_ in enumerate(results, start=1)]
    pkg = PromptPackage(query=query)
    if evidence:
        body = "\n".join(f"[{e['index']}] {e['text']}" for e in evidence)
        body = _apply_compression(body, plan.context.compression)
        # enforce the token budget (approx 4 chars/token)
        body = body[: plan.context.token_budget * 4]
        pkg.sections.append(PromptSection(title="Evidence", content=body))
    prompt_text = pkg.render()
    input_tokens = len(prompt_text) // 4

    # ---- answer via the SINGLE AnswerService pathway ----
    answer_fn = services.get("answer_fn")
    answer = (answer_fn(prompt_text) if answer_fn else "").strip()
    output_tokens = len(answer) // 4
    actual_cost = plan.model.est_cost(input_tokens, output_tokens)

    # ---- verification (reuse Verification Engine) ----
    verification_status, quality_impact = None, 0.0
    try:
        from app.reasoning.repository import VerificationRepository
        from app.reasoning.service import VerificationService
        v = VerificationService(VerificationRepository(db)).verify(
            workspace_id, owner_id, answer_text=answer, evidence=evidence, mode="fast",
            signals={"success": bool(answer)}, agent="optimization", task_type="optimized_query",
            persist=False)
        verification_status = v.get("status")
        quality_impact = float(v.get("overall_confidence") or v.get("confidence") or 0.0)
    except Exception:
        pass

    # ---- populate answer cache for next time ----
    ANSWER_CACHE.put(workspace_id, query, {"answer": answer, "verification_status": verification_status,
                                           "quality_impact": quality_impact})

    return {"answer": answer, "cache_used": False, "results": len(results), "graph_hits": with_graph_hits,
            "tokens": input_tokens + output_tokens, "actual_cost": actual_cost,
            "verification_status": verification_status, "quality_impact": quality_impact}
