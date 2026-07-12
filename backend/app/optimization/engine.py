"""Optimization Engine (Steps 2 & 9) — the automatic stage BEFORE execution.

Composes the profiler → policy → model router → retrieval/context/prompt optimizers → cache check → cost
intelligence into ONE `OptimizationPlan`. This is the "Request → Optimization Engine → Pipeline Selection →
Model Routing → …" flow: the plan fully describes how the pipeline should run (which model, which retrieval/
context/prompt params, whether to serve from cache) plus estimated-vs-baseline cost and explainable
recommendations. Pure decision logic — it runs nothing; `execute.py` applies the plan.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.optimization.cache_intel import ANSWER_CACHE, AnswerCache
from app.optimization.catalog import ModelCatalog
from app.optimization.cost_intel import CostIntelligence
from app.optimization.interfaces import OptimizationPlan
from app.optimization.optimizers import ContextOptimizer, PromptOptimizer, RetrievalOptimizer
from app.optimization.policy import PolicyEngine
from app.optimization.profiler import QueryProfiler
from app.optimization.router import ModelRouter


class OptimizationEngine:
    def __init__(self, *, catalog: Optional[ModelCatalog] = None, answer_cache: Optional[AnswerCache] = None):
        self.catalog = catalog or ModelCatalog()
        self.profiler = QueryProfiler()
        self.policy_engine = PolicyEngine()
        self.router = ModelRouter(self.catalog)
        self.retrieval_opt = RetrievalOptimizer()
        self.context_opt = ContextOptimizer()
        self.prompt_opt = PromptOptimizer()
        self.cost_intel = CostIntelligence(self.catalog)
        self.answer_cache = answer_cache or ANSWER_CACHE

    def optimize(self, workspace_id: str, query: str, *, policy_name: str | None = None) -> OptimizationPlan:
        policy = self.policy_engine.resolve(policy_name)
        weights = self.policy_engine.weights(policy)
        profile = self.profiler.profile(query)

        # cache check first — a hit short-circuits everything downstream
        cache_hit = self.answer_cache.get(workspace_id, query) is not None

        model, candidates, route_rationale = self.router.route(profile, policy, weights)
        retrieval = self.retrieval_opt.optimize(profile, weights)
        context = self.context_opt.optimize(profile, weights, max_compression=policy.get("max_compression", "light"))
        prompt = self.prompt_opt.optimize(profile, weights)

        estimated_cost = 0.0 if cache_hit else model.est_cost(profile.est_context_tokens, profile.est_output_tokens)
        estimated_latency = 5.0 if cache_hit else model.avg_latency_ms
        # baseline = highest-quality model + full pipeline (what LexiMind would do un-optimized)
        baseline_model = self.catalog.best_quality
        baseline_cost = baseline_model.est_cost(int(profile.est_context_tokens * 1.4), profile.est_output_tokens)
        savings = 0.0 if baseline_cost <= 0 else round(max(0.0, 1 - estimated_cost / baseline_cost), 3)

        recs = self.cost_intel.recommendations(profile, model, retrieval, context, cache_hit)
        rationale = (f"{route_rationale} Cache {'HIT' if cache_hit else 'miss'}. "
                     f"Est ${estimated_cost:.5f} vs baseline ${baseline_cost:.5f} "
                     f"({int(savings*100)}% saved).")

        return OptimizationPlan(policy=policy["name"], profile=profile, model=model, retrieval=retrieval,
                                context=context, prompt=prompt,
                                cache_decision="hit" if cache_hit else "miss",
                                estimated_cost=estimated_cost, estimated_latency_ms=estimated_latency,
                                baseline_cost=baseline_cost, estimated_savings=savings,
                                recommendations=recs, candidates=candidates, rationale=rationale)
