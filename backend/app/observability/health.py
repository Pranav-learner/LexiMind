"""Health Monitoring (Step 7) — component health summaries.

Checks the components an AI platform SRE cares about: database reachability, recent error rate (from the
unified telemetry), the in-process caches (Module-2/3/8 caches expose stats), and knowledge-graph
presence. Each check returns ok / degraded / down + a detail; the overall status is the worst component.
Best-effort + cheap — a failing check degrades, it never raises.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select, text
from sqlalchemy.orm import Session

_ORDER = {"ok": 0, "degraded": 1, "down": 2}


def _check(status: str, detail: str = "") -> Dict[str, str]:
    return {"status": status, "detail": detail}


class HealthMonitor:
    def summary(self, db: Session, workspace_id: str, owner_id: str, *,
                error_rate: float = 0.0) -> Dict[str, Any]:
        checks: Dict[str, Dict[str, str]] = {}

        # database
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = _check("ok", "reachable")
        except Exception as e:
            checks["database"] = _check("down", str(e)[:120])

        # error rate (from unified telemetry, passed in)
        if error_rate >= 0.25:
            checks["pipelines"] = _check("degraded", f"error rate {error_rate:.0%}")
        else:
            checks["pipelines"] = _check("ok", f"error rate {error_rate:.0%}")

        # caches (Module-2/3/8 in-process caches)
        checks["cache"] = self._cache_health()

        # knowledge graph presence
        try:
            from app.knowledge.repository import GraphRepository
            n = GraphRepository(db).entity_count(workspace_id, owner_id)
            checks["knowledge_graph"] = _check("ok", f"{n} entities") if n else _check("degraded", "empty graph")
        except Exception:
            checks["knowledge_graph"] = _check("degraded", "unavailable")

        # background workers / LLM availability are declared (best-effort — not probed synchronously)
        checks["workers"] = _check("ok", "threadpool runners")
        checks["llm"] = _check("ok", "answer_service (ollama) — not probed")

        overall = max(checks.values(), key=lambda c: _ORDER.get(c["status"], 0))["status"]
        return {"status": overall, "checks": checks}

    @staticmethod
    def _cache_health() -> Dict[str, str]:
        stats = {}
        try:
            from app.memory.cache import NEIGHBORHOOD_CACHE
            stats["neighborhood"] = NEIGHBORHOOD_CACHE.stats()
        except Exception:
            pass
        try:
            from app.graphreason.cache import REASONING_CACHE
            stats["reasoning"] = REASONING_CACHE.stats()
        except Exception:
            pass
        try:
            from app.evaluation.cache import EVAL_CACHE
            stats["evaluation"] = EVAL_CACHE.stats()
        except Exception:
            pass
        return {"status": "ok", "detail": f"{len(stats)} cache(s) reporting", **{"stats": stats}}
