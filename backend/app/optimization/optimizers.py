"""Stage optimizers (Steps 4, 5, 6) — Retrieval / Context / Prompt.

Each implements the `Optimizer` protocol: (profile, policy weights) → a stage plan of PARAMETERS. They never
replace the Retrieval Engine, Context Engineering, or PromptPackage — they tune how those existing systems
run. Adaptive by complexity + policy: a simple/cost query gets small K, no graph, aggressive compression, a
concise prompt; a complex/research/quality query gets deep retrieval, graph traversal, no compression, a
detailed prompt. Evaluation history can later refine these defaults (advisory hook).
"""

from __future__ import annotations

from typing import Any, Dict

from app.optimization.interfaces import ContextPlan, PromptPlan, RequestProfile, RetrievalPlan


def _cost_leaning(weights: Dict[str, float]) -> bool:
    return weights.get("cost", 0.0) >= 0.5


def _quality_leaning(weights: Dict[str, float]) -> bool:
    return weights.get("quality", 0.0) >= 0.5


# --------------------------------------------------------------------- Step 4: Retrieval Optimizer
class RetrievalOptimizer:
    def optimize(self, profile: RequestProfile, weights: Dict[str, float]) -> RetrievalPlan:
        c = profile.complexity
        top_k = 4 if profile.tier == "simple" else (8 if profile.tier == "moderate" else 12)
        rerank_depth = 0 if profile.tier == "simple" else int(round(15 + 25 * c))
        # dense weight rises with complexity (semantic queries lean dense; keyword queries lean sparse)
        hybrid_alpha = round(min(0.85, 0.4 + 0.45 * c), 2)
        use_graph = profile.is_research or profile.tier == "complex"
        graph_hops = 3 if profile.is_research else (2 if use_graph else 0)
        early_stop = profile.tier == "simple" or _cost_leaning(weights)

        if _cost_leaning(weights):                          # cost policy trims everything
            top_k = max(3, top_k - 2)
            rerank_depth = 0
            if not profile.is_research:
                use_graph, graph_hops = False, 0
        elif _quality_leaning(weights):                     # quality policy widens the funnel
            top_k += 2
            rerank_depth = max(rerank_depth, 25)
            use_graph, graph_hops = True, max(graph_hops, 2)

        bits = [f"k={top_k}", ("rerank off" if not rerank_depth else f"rerank@{rerank_depth}"),
                (f"graph×{graph_hops}" if use_graph else "no graph"),
                ("early-stop" if early_stop else "full")]
        return RetrievalPlan(top_k=top_k, rerank_depth=rerank_depth, hybrid_alpha=hybrid_alpha,
                             graph_hops=graph_hops, use_graph=use_graph, early_stop=early_stop,
                             use_cache=True, rationale=", ".join(bits))


# --------------------------------------------------------------------- Step 5: Context Optimizer
class ContextOptimizer:
    _LEVELS = {"none": 0, "light": 1, "aggressive": 2}

    def optimize(self, profile: RequestProfile, weights: Dict[str, float],
                 *, max_compression: str = "light") -> ContextPlan:
        budget = int(1200 + 3000 * profile.complexity)     # simple ≈1200, complex ≈4200
        compression = "none"
        if _cost_leaning(weights):
            compression = "aggressive"
            budget = int(budget * 0.6)
        elif _quality_leaning(weights):
            compression = "none"
        else:
            compression = "light" if profile.complexity < 0.7 else "none"

        # cap by the policy's max allowed compression (e.g. research/highest_quality → none)
        cap = self._LEVELS.get(max_compression, 1)
        if self._LEVELS.get(compression, 0) > cap:
            compression = max_compression
        preserve_citations = True                           # never drop citations (quality invariant)
        rationale = f"budget≈{budget}tok, {compression} compression, dedup, citations preserved"
        return ContextPlan(token_budget=budget, compression=compression, dedup=True,
                           preserve_citations=preserve_citations, rationale=rationale)


# --------------------------------------------------------------------- Step 6: Prompt Optimizer
class PromptOptimizer:
    def optimize(self, profile: RequestProfile, weights: Dict[str, float]) -> PromptPlan:
        if _cost_leaning(weights) or profile.tier == "simple":
            template = "concise"
        elif profile.is_research or _quality_leaning(weights):
            template = "detailed"
        else:
            template = "standard"
        compress = _cost_leaning(weights)
        rationale = f"{template} template" + (", compressed" if compress else "")
        return PromptPlan(template=template, version="v1", compress=compress, rationale=rationale)
