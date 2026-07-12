"""Cost Intelligence Engine (Step 8).

Generates EXPLAINABLE, actionable recommendations from an optimization plan + the observability cost report.
Every recommendation carries a why + an estimated saving so a human (or a future auto-optimizer) can act:
"switch to a cheaper model", "reuse the cached answer", "compress context", "reduce graph depth", "skip the
reranker". It reuses the M2 CostTracker for the historical cost picture rather than recomputing it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.optimization.catalog import ModelCatalog
from app.optimization.interfaces import ModelSpec, OptimizationPlan, Recommendation, RequestProfile


class CostIntelligence:
    def __init__(self, catalog: ModelCatalog | None = None):
        self.catalog = catalog or ModelCatalog()

    def recommendations(self, profile: RequestProfile, model: ModelSpec, retrieval, context,
                        cache_hit: bool) -> List[Recommendation]:
        recs: List[Recommendation] = []

        # 1) reuse cached answer — the biggest lever
        if cache_hit:
            recs.append(Recommendation("reuse_cache", "This query matches a cached answer — serve it and "
                                       "skip retrieval + inference entirely.", estimated_savings=1.0,
                                       action={"serve_from_cache": True}))
            return recs                                   # nothing else matters if we can cache-hit

        # 2) cheaper model with acceptable quality
        cur_cost = model.est_cost(profile.est_context_tokens, profile.est_output_tokens)
        floor = max(0.0, profile.quality_requirement - 0.15)
        cheaper = [m for m in self.catalog.available()
                   if m.quality >= floor and m.name != model.name
                   and m.est_cost(profile.est_context_tokens, profile.est_output_tokens) < cur_cost]
        if cheaper:
            alt = min(cheaper, key=lambda m: m.est_cost(profile.est_context_tokens, profile.est_output_tokens))
            alt_cost = alt.est_cost(profile.est_context_tokens, profile.est_output_tokens)
            save = 0.0 if cur_cost <= 0 else round(1 - alt_cost / cur_cost, 3)
            if save > 0.05:
                recs.append(Recommendation("model_switch",
                            f"Switch to {alt.name} (quality {alt.quality}) to cut ~{int(save*100)}% of "
                            f"per-request cost at acceptable quality.", estimated_savings=save,
                            action={"model": alt.name}))

        # 3) compress context if large + not already compressed
        if context.compression == "none" and profile.est_context_tokens > 2500:
            recs.append(Recommendation("compress_context", "Context is large; enable light compression to "
                                       "reduce input tokens without losing citations.",
                                       estimated_savings=0.2, action={"compression": "light"}))

        # 4) reduce graph depth on non-research queries
        if retrieval.use_graph and retrieval.graph_hops >= 3 and not profile.is_research:
            recs.append(Recommendation("reduce_graph", "Graph traversal depth exceeds what this query needs; "
                                       "reduce hops to cut retrieval latency/cost.", estimated_savings=0.1,
                                       action={"graph_hops": 2}))

        # 5) skip reranker on simple queries
        if retrieval.rerank_depth and profile.tier == "simple":
            recs.append(Recommendation("skip_reranker", "Simple query — the reranker adds cost without "
                                       "changing the top result; skip it.", estimated_savings=0.08,
                                       action={"rerank_depth": 0}))
        return recs

    def analyze(self, cost_report: Dict[str, Any]) -> Dict[str, Any]:
        """Fold the observability cost report into an optimization-facing summary."""
        by_source = cost_report.get("by_source", {})
        top = sorted(by_source.items(), key=lambda kv: kv[1].get("cost", 0), reverse=True)[:5]
        return {"total_tokens": cost_report.get("total_tokens", 0),
                "total_cost": cost_report.get("total_cost", 0.0),
                "avg_cost_per_request": cost_report.get("avg_cost_per_request", 0.0),
                "top_cost_sources": [{"source": s, "cost": v.get("cost", 0), "tokens": v.get("tokens", 0)}
                                     for s, v in top]}
