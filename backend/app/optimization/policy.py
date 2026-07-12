"""Policy Engine (Step 15) — configurable optimization objectives.

A policy is a named set of weights over (cost, quality, latency) plus flags that constrain the optimizers
(e.g. offline forces local models). Policies are configurable per workspace (persisted `WorkspacePolicy`);
future ML-based policies plug in by producing the same weight vector, so the router/optimizers never change.
"""

from __future__ import annotations

from typing import Any, Dict

# name -> {weights + flags}. Weights are relative; the router normalizes.
POLICIES: Dict[str, Dict[str, Any]] = {
    "balanced":        {"cost": 0.35, "quality": 0.40, "latency": 0.25, "offline": False, "max_compression": "light"},
    "lowest_cost":     {"cost": 0.70, "quality": 0.15, "latency": 0.15, "offline": False, "max_compression": "aggressive"},
    "highest_quality": {"cost": 0.10, "quality": 0.80, "latency": 0.10, "offline": False, "max_compression": "none"},
    "fastest":         {"cost": 0.20, "quality": 0.20, "latency": 0.60, "offline": False, "max_compression": "aggressive"},
    "research":        {"cost": 0.15, "quality": 0.70, "latency": 0.15, "offline": False, "max_compression": "none"},
    "offline":         {"cost": 0.40, "quality": 0.35, "latency": 0.25, "offline": True,  "max_compression": "light"},
    "developer":       {"cost": 0.30, "quality": 0.45, "latency": 0.25, "offline": False, "max_compression": "light"},
    "enterprise":      {"cost": 0.30, "quality": 0.50, "latency": 0.20, "offline": False, "max_compression": "light"},
}

DEFAULT_POLICY = "balanced"
POLICY_VERSION = "policy-v1"


class PolicyEngine:
    """Resolves a policy name to weights/flags, with per-workspace overrides."""

    def resolve(self, name: str | None) -> Dict[str, Any]:
        policy = POLICIES.get((name or DEFAULT_POLICY), POLICIES[DEFAULT_POLICY])
        return {**policy, "name": name if name in POLICIES else DEFAULT_POLICY, "version": POLICY_VERSION}

    def names(self) -> list[str]:
        return list(POLICIES.keys())

    @staticmethod
    def weights(policy: Dict[str, Any]) -> Dict[str, float]:
        total = policy["cost"] + policy["quality"] + policy["latency"] or 1.0
        return {"cost": policy["cost"] / total, "quality": policy["quality"] / total,
                "latency": policy["latency"] / total}
