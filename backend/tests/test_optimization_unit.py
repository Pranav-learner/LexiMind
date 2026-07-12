"""Unit tests for the Phase-8 Module-3 Optimization platform — pure/offline (no HTTP, no LLM).

Covers the query profiler, model router (policy-weighted + offline + context-fit), the retrieval/context/
prompt optimizers, the answer cache (LRU + TTL), the cost-intelligence recommendations, and the policy
engine.
"""

from __future__ import annotations

from app.optimization.cache_intel import AnswerCache, CacheIntelligence
from app.optimization.catalog import ModelCatalog
from app.optimization.cost_intel import CostIntelligence
from app.optimization.engine import OptimizationEngine
from app.optimization.interfaces import RequestProfile
from app.optimization.optimizers import ContextOptimizer, PromptOptimizer, RetrievalOptimizer
from app.optimization.policy import PolicyEngine
from app.optimization.profiler import QueryProfiler
from app.optimization.router import ModelRouter


# --------------------------------------------------------------------- profiler
def test_profiler_tiers():
    p = QueryProfiler()
    simple = p.profile("what is X?")
    complex_ = p.profile("Compare and analyze the tradeoffs and implications of A versus B across "
                         "distributed systems and explain why one is better and how it scales")
    assert simple.tier == "simple" and simple.complexity < complex_.complexity
    assert complex_.tier in ("moderate", "complex") and complex_.is_research
    assert complex_.est_context_tokens > simple.est_context_tokens


# --------------------------------------------------------------------- router
def test_router_respects_policy():
    router = ModelRouter(ModelCatalog())
    pe = PolicyEngine()
    profile = QueryProfiler().profile("explain caching")
    cheap = router.route(profile, pe.resolve("lowest_cost"), pe.weights(pe.resolve("lowest_cost")))[0]
    quality = router.route(profile, pe.resolve("highest_quality"), pe.weights(pe.resolve("highest_quality")))[0]
    # lowest_cost picks a cheaper model than highest_quality
    assert cheap.est_cost(1000, 400) <= quality.est_cost(1000, 400)


def test_router_offline_forces_local():
    router = ModelRouter(ModelCatalog())
    pe = PolicyEngine()
    pol = pe.resolve("offline")
    model, candidates, _ = router.route(QueryProfiler().profile("hi"), pol, pe.weights(pol))
    assert model.local and all(ModelCatalog().get(c["model"]).local for c in candidates)


# --------------------------------------------------------------------- stage optimizers
def test_retrieval_optimizer_adapts():
    ro = RetrievalOptimizer()
    pe = PolicyEngine()
    simple = ro.optimize(QueryProfiler().profile("define X"), pe.weights(pe.resolve("lowest_cost")))
    research = ro.optimize(RequestProfile(query="q", complexity=0.9, tier="complex", is_research=True),
                          pe.weights(pe.resolve("highest_quality")))
    assert simple.top_k < research.top_k and not simple.use_graph and research.use_graph
    assert simple.early_stop and research.graph_hops >= 2


def test_context_optimizer_caps_compression_by_policy():
    co = ContextOptimizer()
    pe = PolicyEngine()
    profile = RequestProfile(query="q", complexity=0.8, tier="complex")
    # research policy forbids compression
    plan = co.optimize(profile, pe.weights(pe.resolve("research")), max_compression="none")
    assert plan.compression == "none" and plan.preserve_citations
    cost = co.optimize(profile, pe.weights(pe.resolve("lowest_cost")), max_compression="aggressive")
    assert cost.compression == "aggressive" and cost.token_budget < plan.token_budget


def test_prompt_optimizer_selects_template():
    po = PromptOptimizer()
    pe = PolicyEngine()
    assert po.optimize(QueryProfiler().profile("hi"), pe.weights(pe.resolve("lowest_cost"))).template == "concise"
    assert po.optimize(RequestProfile(query="q", is_research=True, complexity=0.8, tier="complex"),
                       pe.weights(pe.resolve("research"))).template == "detailed"


# --------------------------------------------------------------------- answer cache
def test_answer_cache_lru_and_ttl():
    c = AnswerCache(capacity=2, ttl_seconds=100)
    c.put("ws", "q1", {"answer": "a1"}, now=0)
    c.put("ws", "q2", {"answer": "a2"}, now=0)
    assert c.get("ws", "q1", now=1)["answer"] == "a1"     # hit
    c.put("ws", "q3", {"answer": "a3"}, now=1)            # evicts q2 (LRU)
    assert c.get("ws", "q2", now=1) is None
    assert c.get("ws", "q1", now=999) is None             # expired (TTL)
    assert c.stats()["hits"] >= 1 and "hit_rate" in c.stats()


# --------------------------------------------------------------------- cost intelligence
def test_cost_intel_recommendations():
    ci = CostIntelligence(ModelCatalog())
    profile = RequestProfile(query="q", complexity=0.9, tier="complex", quality_requirement=0.7,
                            est_context_tokens=3000, est_output_tokens=600)
    expensive = ModelCatalog().get("claude-opus-4-8")
    ro = RetrievalOptimizer().optimize(profile, {"cost": 0.1, "quality": 0.8, "latency": 0.1})
    co = ContextOptimizer().optimize(profile, {"cost": 0.1, "quality": 0.8, "latency": 0.1}, max_compression="none")
    recs = ci.recommendations(profile, expensive, ro, co, cache_hit=False)
    kinds = {r.kind for r in recs}
    assert "model_switch" in kinds                        # a cheaper model exists at acceptable quality
    # cache hit short-circuits to a single reuse_cache rec
    hit = ci.recommendations(profile, expensive, ro, co, cache_hit=True)
    assert len(hit) == 1 and hit[0].kind == "reuse_cache" and hit[0].estimated_savings == 1.0


# --------------------------------------------------------------------- engine + policy
def test_engine_plan_and_savings():
    eng = OptimizationEngine()
    plan = eng.optimize("ws", "what is a deadlock?", policy_name="lowest_cost")
    assert plan.estimated_savings > 0 and plan.estimated_cost < plan.baseline_cost
    assert plan.candidates and plan.model.name == plan.candidates[0]["model"]
    d = plan.to_dict()
    assert d["policy"] == "lowest_cost" and "retrieval" in d and "recommendations" in d


def test_policy_engine_weights_normalize():
    pe = PolicyEngine()
    w = pe.weights(pe.resolve("balanced"))
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert pe.resolve("nonsense")["name"] == "balanced"   # unknown → default
    assert set(pe.names()) >= {"lowest_cost", "highest_quality", "offline", "enterprise"}
