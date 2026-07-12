"""Model Router (Step 3) — intelligent, provider-agnostic model selection.

Given a request profile + policy weights, scores every available model by a normalized cost/quality/latency
tradeoff (filtered by availability, offline flag, context-fit, and a quality floor from the request), then
returns the optimal model + per-candidate scores + a human rationale. Never hardcodes providers — it scores
whatever the `ModelCatalog` (a `ModelProvider`) exposes, so new providers/models plug in for free.

The router SELECTS a model; LexiMind's actual inference still flows through the single AnswerService
pathway. The selection drives cost estimates + recommendations (and, once provider clients are wired behind
the catalog abstraction, the execution target).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.optimization.catalog import ModelCatalog
from app.optimization.interfaces import ModelSpec, RequestProfile


class ModelRouter:
    def __init__(self, catalog: ModelCatalog | None = None):
        self.catalog = catalog or ModelCatalog()

    def route(self, profile: RequestProfile, policy: Dict[str, Any], weights: Dict[str, float]
              ) -> Tuple[ModelSpec, List[Dict[str, Any]], str]:
        candidates = self.catalog.available(offline_only=bool(policy.get("offline")))
        # context-fit + quality floor (a complex/research request won't accept a weak model)
        floor = max(0.0, profile.quality_requirement - 0.25)
        fitted = [m for m in candidates
                  if m.max_context >= profile.est_context_tokens and m.quality >= floor]
        pool = fitted or candidates                       # never return nothing

        # normalization ranges across the pool
        costs = [m.est_cost(profile.est_context_tokens, profile.est_output_tokens) for m in pool]
        lats = [m.avg_latency_ms for m in pool]
        cmin, cmax = min(costs), max(costs)
        lmin, lmax = min(lats), max(lats)

        def _norm(v, lo, hi):                              # 1.0 = best (cheapest/fastest), 0 = worst
            return 1.0 if hi == lo else (hi - v) / (hi - lo)

        scored: List[Dict[str, Any]] = []
        for m in pool:
            cost = m.est_cost(profile.est_context_tokens, profile.est_output_tokens)
            score = (weights["cost"] * _norm(cost, cmin, cmax)
                     + weights["quality"] * m.quality
                     + weights["latency"] * _norm(m.avg_latency_ms, lmin, lmax))
            scored.append({"model": m.name, "provider": m.provider, "score": round(score, 4),
                           "est_cost": round(cost, 6), "quality": m.quality, "latency_ms": m.avg_latency_ms})
        scored.sort(key=lambda s: s["score"], reverse=True)
        best = self.catalog.get(scored[0]["model"])
        rationale = (f"Policy '{policy.get('name')}' weights cost={weights['cost']:.2f}/"
                     f"quality={weights['quality']:.2f}/latency={weights['latency']:.2f}; "
                     f"{best.name} wins for a {profile.tier} query "
                     f"(quality {best.quality}, est ${scored[0]['est_cost']:.5f}).")
        return best, scored, rationale
