"""Multimodal context data access — the ContextBuildLog writes + observability aggregation."""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.mmcontext.models import ContextBuildLog


class ContextRepository:
    def __init__(self, db: Session):
        self.db = db

    def log_build(self, log: ContextBuildLog) -> None:
        self.db.add(log)
        self.db.commit()

    def observability(self, workspace_id: str, *, limit_recent: int = 10) -> Dict:
        def avg(col):
            return float(self.db.scalar(select(func.coalesce(func.avg(col), 0.0))
                                        .where(ContextBuildLog.workspace_id == workspace_id)) or 0.0)
        total = int(self.db.scalar(select(func.count()).select_from(ContextBuildLog)
                                   .where(ContextBuildLog.workspace_id == workspace_id)) or 0)
        rows = list(self.db.scalars(select(ContextBuildLog).where(ContextBuildLog.workspace_id == workspace_id)
                                    .order_by(desc(ContextBuildLog.created_at)).limit(200)))
        usage: Dict[str, int] = {}
        for r in rows:
            usage[r.primary_intent] = usage.get(r.primary_intent, 0) + 1
        recent: List[dict] = [{
            "query": r.query[:120], "primary_intent": r.primary_intent, "included": r.included,
            "context_tokens": r.context_tokens, "compression_ratio": round(r.compression_ratio, 3),
            "duplicate_reduction": round(r.duplicate_reduction, 3), "total_ms": round(r.total_ms, 2),
        } for r in rows[:limit_recent]]
        return {
            "builds": total, "avg_total_ms": round(avg(ContextBuildLog.total_ms), 2),
            "avg_compression_ratio": round(avg(ContextBuildLog.compression_ratio), 3),
            "avg_duplicate_reduction": round(avg(ContextBuildLog.duplicate_reduction), 3),
            "avg_context_tokens": round(avg(ContextBuildLog.context_tokens), 1),
            "intent_usage": usage, "recent": recent,
        }
