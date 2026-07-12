"""Provider-agnostic model catalog (Step 3 foundation).

The catalog is a `ModelProvider` behind an abstraction — never a hardcoded `if provider == "openai"`. Each
entry is a `ModelSpec` (cost/quality/latency/context/availability); the router scores them by policy. New
providers register by adding specs, not by editing routing logic.

NOTE ON PRICING: the Anthropic entries use current model IDs and list pricing (per-1M → per-1k). The
OpenAI/Google entries are REPRESENTATIVE illustrative rates for a routing demonstration — LexiMind's actual
inference always flows through the single AnswerService pathway (local by default); the router SELECTS a
model + estimates cost, it does not itself call external providers. Wiring a spec to a real provider client
is a drop-in behind this abstraction (future work).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.optimization.interfaces import ModelSpec

# per-1k token rates (USD). Anthropic = list price / 1000; others = representative.
_CATALOG: List[ModelSpec] = [
    # local (Ollama) — zero marginal cost, the AnswerService default
    ModelSpec("llama3-local", "local", 0.0, 0.0, quality=0.60, avg_latency_ms=850, max_context=8192, local=True),
    # Anthropic (current IDs + list pricing)
    ModelSpec("claude-haiku-4-5", "anthropic", 0.001, 0.005, quality=0.78, avg_latency_ms=500, max_context=200000),
    ModelSpec("claude-sonnet-5", "anthropic", 0.003, 0.015, quality=0.92, avg_latency_ms=800, max_context=1000000),
    ModelSpec("claude-opus-4-8", "anthropic", 0.005, 0.025, quality=0.97, avg_latency_ms=1100, max_context=1000000),
    # OpenAI (representative)
    ModelSpec("gpt-4o-mini", "openai", 0.00015, 0.0006, quality=0.74, avg_latency_ms=600, max_context=128000),
    ModelSpec("gpt-4o", "openai", 0.0025, 0.01, quality=0.90, avg_latency_ms=900, max_context=128000),
    # Google (representative)
    ModelSpec("gemini-flash", "google", 0.0001, 0.0004, quality=0.72, avg_latency_ms=500, max_context=1000000),
]


class ModelCatalog:
    """A pluggable `ModelProvider` over the static specs (future: merge live provider health)."""

    def __init__(self, specs: Optional[List[ModelSpec]] = None):
        self._specs = list(specs if specs is not None else _CATALOG)

    def models(self) -> List[ModelSpec]:
        return list(self._specs)

    def available(self, *, offline_only: bool = False) -> List[ModelSpec]:
        return [m for m in self._specs if m.available and (m.local if offline_only else True)]

    def get(self, name: str) -> Optional[ModelSpec]:
        return next((m for m in self._specs if m.name == name), None)

    @property
    def cheapest(self) -> ModelSpec:
        return min(self._specs, key=lambda m: m.output_cost_per_1k)

    @property
    def best_quality(self) -> ModelSpec:
        return max(self._specs, key=lambda m: m.quality)


def default_catalog() -> ModelCatalog:
    return ModelCatalog()
