"""Optimization service — orchestrates preview, recommendations, execution, cost analysis, policy, cache.

Composes the Optimization Engine (decision), the optimized executor (apply through the real pipeline), the
observability CostTracker (historical cost — reused, not recomputed), and the cache/cost intelligence into
the API surface. The only writes are new OptimizationRunLog rows + the per-workspace policy — everything else
reads existing telemetry.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.optimization.cache_intel import CacheIntelligence
from app.optimization.cost_intel import CostIntelligence
from app.optimization.engine import OptimizationEngine
from app.optimization.errors import UnknownPolicy
from app.optimization.models import OptimizationRunLog
from app.optimization.policy import PolicyEngine
from app.optimization.repository import OptimizationRepository


class OptimizationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = OptimizationRepository(db)
        self.engine = OptimizationEngine()
        self.policy_engine = PolicyEngine()
        self.cache_intel = CacheIntelligence()
        self.cost_intel = CostIntelligence()

    # ------------------------------------------------------------------ policy resolution
    def _effective_policy(self, workspace_id: str, owner_id: str, requested: Optional[str]) -> str:
        if requested:
            if requested not in self.policy_engine.names():
                raise UnknownPolicy(requested, self.policy_engine.names())
            return requested
        row = self.repo.get_policy(workspace_id, owner_id)
        return row.policy if row else None                # None → engine default

    # ------------------------------------------------------------------ preview (no execution)
    def preview(self, workspace_id, owner_id, *, query, policy=None) -> Dict[str, Any]:
        name = self._effective_policy(workspace_id, owner_id, policy)
        return self.engine.optimize(workspace_id, query, policy_name=name).to_dict()

    def recommend_model(self, workspace_id, owner_id, *, query, policy=None) -> Dict[str, Any]:
        plan = self.engine.optimize(workspace_id, query,
                                    policy_name=self._effective_policy(workspace_id, owner_id, policy))
        return {"selected": plan.model.to_dict(), "candidates": plan.candidates, "rationale": plan.rationale,
                "profile": plan.profile.to_dict()}

    def recommend_pipeline(self, workspace_id, owner_id, *, query, policy=None) -> Dict[str, Any]:
        plan = self.engine.optimize(workspace_id, query,
                                    policy_name=self._effective_policy(workspace_id, owner_id, policy))
        return {"tier": plan.profile.tier, "model": plan.model.name, "retrieval": plan.retrieval.to_dict(),
                "context": plan.context.to_dict(), "prompt": plan.prompt.to_dict(),
                "cache_decision": plan.cache_decision, "recommendations": [r.to_dict() for r in plan.recommendations]}

    # ------------------------------------------------------------------ optimized execution
    def run_optimized(self, workspace_id, owner_id, *, query, services, policy=None) -> Dict[str, Any]:
        from app.optimization.execute import apply_plan
        name = self._effective_policy(workspace_id, owner_id, policy)
        plan = self.engine.optimize(workspace_id, query, policy_name=name)
        result = apply_plan(self.db, workspace_id, owner_id, plan=plan, services=services)

        actual_cost = float(result.get("actual_cost", 0.0))
        savings = 0.0 if plan.baseline_cost <= 0 else round(max(0.0, 1 - actual_cost / plan.baseline_cost), 3)
        run = OptimizationRunLog(
            id=f"optrun_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            query=query[:2000], policy=plan.policy, policy_version=self.policy_engine.resolve(name)["version"],
            tier=plan.profile.tier, model_selected=plan.model.name,
            retrieval_policy=json.dumps(plan.retrieval.to_dict()), compression=plan.context.compression,
            prompt_version=plan.prompt.version, cache_used=bool(result.get("cache_used")),
            estimated_cost=plan.estimated_cost, actual_cost=actual_cost, baseline_cost=plan.baseline_cost,
            savings=savings, tokens=int(result.get("tokens", 0)),
            latency_ms=plan.estimated_latency_ms, quality_impact=float(result.get("quality_impact", 0.0)))
        self.repo.save_run(run)
        return {"plan": plan.to_dict(), "result": result, "run_id": run.id, "savings": savings}

    # ------------------------------------------------------------------ cost analysis (reuses observability)
    def cost_analysis(self, workspace_id, owner_id) -> Dict[str, Any]:
        from app.observability.unifier import TelemetryUnifier
        events = TelemetryUnifier(self.db).events(workspace_id, owner_id, limit=2000)
        from app.observability.cost import CostTracker
        cost_report = CostTracker().report(events)
        analysis = self.cost_intel.analyze(cost_report)
        # optimization-run savings summary
        runs = self.repo.runs(workspace_id, owner_id, limit=200)
        realized = [r.savings for r in runs if not r.cache_used]
        cached = sum(1 for r in runs if r.cache_used)
        analysis["optimization"] = {
            "runs": len(runs), "cache_hits": cached,
            "avg_savings": round(sum(realized) / len(realized), 3) if realized else 0.0,
            "total_estimated_cost": round(sum(r.estimated_cost for r in runs), 6),
            "total_baseline_cost": round(sum(r.baseline_cost for r in runs), 6)}
        return analysis

    def quality_vs_cost(self, workspace_id, owner_id) -> Dict[str, Any]:
        runs = self.repo.runs(workspace_id, owner_id, limit=200)
        points = [{"model": r.model_selected, "cost": round(r.actual_cost, 6), "quality": r.quality_impact,
                   "policy": r.policy, "tier": r.tier, "savings": r.savings,
                   "latency_ms": r.latency_ms, "cache_used": r.cache_used} for r in runs]
        return {"points": points, "count": len(points)}

    # ------------------------------------------------------------------ history / policy / cache
    def history(self, workspace_id, owner_id, *, limit=50) -> List[Dict[str, Any]]:
        return [{"id": r.id, "query": r.query[:160], "policy": r.policy, "tier": r.tier,
                 "model": r.model_selected, "compression": r.compression, "cache_used": r.cache_used,
                 "estimated_cost": round(r.estimated_cost, 6), "actual_cost": round(r.actual_cost, 6),
                 "baseline_cost": round(r.baseline_cost, 6), "savings": r.savings, "tokens": r.tokens,
                 "quality_impact": r.quality_impact,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in self.repo.runs(workspace_id, owner_id, limit=limit)]

    def get_policy(self, workspace_id, owner_id) -> Dict[str, Any]:
        row = self.repo.get_policy(workspace_id, owner_id)
        current = row.policy if row else "balanced"
        return {"current": current, "available": self.policy_engine.names(),
                "resolved": self.policy_engine.resolve(current)}

    def set_policy(self, workspace_id, owner_id, *, policy) -> Dict[str, Any]:
        if policy not in self.policy_engine.names():
            raise UnknownPolicy(policy, self.policy_engine.names())
        row = self.repo.set_policy(workspace_id, owner_id, policy)
        return {"current": row.policy, "available": self.policy_engine.names()}

    def cache_stats(self, workspace_id, owner_id) -> Dict[str, Any]:
        return self.cache_intel.report()

    def dashboard(self, workspace_id, owner_id) -> Dict[str, Any]:
        return {"policy": self.get_policy(workspace_id, owner_id),
                "cost_analysis": self.cost_analysis(workspace_id, owner_id),
                "cache": self.cache_stats(workspace_id, owner_id),
                "recent_runs": self.history(workspace_id, owner_id, limit=10),
                "quality_vs_cost": self.quality_vs_cost(workspace_id, owner_id)["points"][:20]}
