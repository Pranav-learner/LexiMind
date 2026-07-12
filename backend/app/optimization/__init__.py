"""AI Optimization & Cost Intelligence Platform (Phase 8, Module 3) — the self-optimizing layer.

Optimization becomes an automatic stage BEFORE execution: Request → Optimization Engine → model routing +
retrieval/context/prompt optimization + cache decision → apply through the REAL pipeline → record savings.
It CONSUMES the Evaluation & Observability signals and TUNES the existing Retrieval / Context / PromptPackage
/ AnswerService / Verification systems — never duplicating or bypassing them.

    interfaces.py    RequestProfile / ModelSpec / RetrievalPlan / ContextPlan / PromptPlan / OptimizationPlan
                     + Optimizer / ModelProvider protocols
    catalog.py       ModelCatalog — provider-agnostic model specs (cost/quality/latency)
    policy.py        PolicyEngine — named policies → weights (lowest_cost / highest_quality / balanced / …)
    profiler.py      QueryProfiler — deterministic complexity estimation
    router.py        ModelRouter — policy-weighted, context-fit model selection
    optimizers.py    Retrieval / Context / Prompt optimizers (adaptive params)
    cache_intel.py   AnswerCache + CacheIntelligence (aggregates existing caches)
    cost_intel.py    CostIntelligence — explainable cost recommendations
    engine.py        OptimizationEngine — composes all of the above into one OptimizationPlan
    execute.py       apply_plan — runs the plan through the real retrieval→answer→verify pipeline
    models.py        OptimizationRunLog + WorkspacePolicy
    repository/service/schemas/api/errors  data access + orchestration + DTOs + routes
"""
