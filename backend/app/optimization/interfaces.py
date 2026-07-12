"""Value objects + Protocols for the Optimization & Cost Intelligence platform (Phase 8, Module 3).

Interface-driven: every optimizer (model router, retrieval/context/prompt optimizers) implements the
`Optimizer` protocol, so future optimizers plug in without touching the engine. The plans are pure data
(dataclasses with to_dict) — the engine PRODUCES them, execution APPLIES them; the two are decoupled so an
optimization can be previewed without running anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# --------------------------------------------------------------------- request profile
@dataclass
class RequestProfile:
    """A normalized read of the request the engine optimizes against."""
    query: str
    complexity: float = 0.5              # 0..1
    tier: str = "moderate"               # simple | moderate | complex
    est_context_tokens: int = 1000
    est_output_tokens: int = 400
    quality_requirement: float = 0.6     # 0..1 (how much quality matters for this request)
    is_research: bool = False
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"query": self.query[:200], "complexity": round(self.complexity, 3), "tier": self.tier,
                "est_context_tokens": self.est_context_tokens, "est_output_tokens": self.est_output_tokens,
                "quality_requirement": round(self.quality_requirement, 3), "is_research": self.is_research,
                "keywords": self.keywords[:12]}


# --------------------------------------------------------------------- model spec (provider-agnostic)
@dataclass
class ModelSpec:
    name: str
    provider: str                        # anthropic | openai | google | local | ...
    input_cost_per_1k: float
    output_cost_per_1k: float
    quality: float                       # 0..1 relative capability
    avg_latency_ms: float
    max_context: int
    local: bool = False
    available: bool = True

    def est_cost(self, in_tokens: int, out_tokens: int) -> float:
        return (in_tokens / 1000.0) * self.input_cost_per_1k + (out_tokens / 1000.0) * self.output_cost_per_1k

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "provider": self.provider, "input_cost_per_1k": self.input_cost_per_1k,
                "output_cost_per_1k": self.output_cost_per_1k, "quality": self.quality,
                "avg_latency_ms": self.avg_latency_ms, "max_context": self.max_context,
                "local": self.local, "available": self.available}


# --------------------------------------------------------------------- stage plans
@dataclass
class RetrievalPlan:
    top_k: int = 8
    rerank_depth: int = 20
    hybrid_alpha: float = 0.5            # dense weight (1-alpha = sparse)
    graph_hops: int = 2
    use_graph: bool = True
    early_stop: bool = False
    use_cache: bool = True
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"top_k": self.top_k, "rerank_depth": self.rerank_depth, "hybrid_alpha": self.hybrid_alpha,
                "graph_hops": self.graph_hops, "use_graph": self.use_graph, "early_stop": self.early_stop,
                "use_cache": self.use_cache, "rationale": self.rationale}


@dataclass
class ContextPlan:
    token_budget: int = 3000
    compression: str = "none"            # none | light | aggressive
    dedup: bool = True
    preserve_citations: bool = True
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"token_budget": self.token_budget, "compression": self.compression, "dedup": self.dedup,
                "preserve_citations": self.preserve_citations, "rationale": self.rationale}


@dataclass
class PromptPlan:
    template: str = "standard"           # concise | standard | detailed
    version: str = "v1"
    compress: bool = False
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"template": self.template, "version": self.version, "compress": self.compress,
                "rationale": self.rationale}


@dataclass
class Recommendation:
    kind: str                            # model_switch | reuse_cache | compress_context | reduce_graph | skip_reranker
    message: str
    estimated_savings: float = 0.0       # fraction 0..1
    action: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "message": self.message,
                "estimated_savings": round(self.estimated_savings, 3), "action": self.action or {}}


@dataclass
class OptimizationPlan:
    policy: str
    profile: RequestProfile
    model: ModelSpec
    retrieval: RetrievalPlan
    context: ContextPlan
    prompt: PromptPlan
    cache_decision: str = "miss"         # miss | hit
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    baseline_cost: float = 0.0
    estimated_savings: float = 0.0       # fraction vs baseline
    recommendations: List[Recommendation] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"policy": self.policy, "profile": self.profile.to_dict(), "model": self.model.to_dict(),
                "retrieval": self.retrieval.to_dict(), "context": self.context.to_dict(),
                "prompt": self.prompt.to_dict(), "cache_decision": self.cache_decision,
                "estimated_cost": round(self.estimated_cost, 6),
                "estimated_latency_ms": round(self.estimated_latency_ms, 1),
                "baseline_cost": round(self.baseline_cost, 6),
                "estimated_savings": round(self.estimated_savings, 3),
                "recommendations": [r.to_dict() for r in self.recommendations],
                "candidates": self.candidates, "rationale": self.rationale}


# --------------------------------------------------------------------- protocols (pluggable optimizers)
@runtime_checkable
class Optimizer(Protocol):
    """Any stage optimizer: given a profile + policy weights, produce a stage plan."""
    def optimize(self, profile: RequestProfile, weights: Dict[str, float]) -> Any: ...


@runtime_checkable
class ModelProvider(Protocol):
    """Abstracts a model catalog so future providers plug in without hardcoding."""
    def models(self) -> List[ModelSpec]: ...
