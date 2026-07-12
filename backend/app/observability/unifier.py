"""Telemetry Unifier (Step 11) — a normalized VIEW over the telemetry every module already writes.

The observability platform does NOT re-log. It READS the existing per-module log tables (RetrievalLog /
AgentExecutionLog / AgentTaskLog / OrchestrationExecutionLog / VerificationLog / GraphReasoningLog /
SemanticMemoryLog / GraphConstructionLog / RetrievalLog / TemporalSearchLog / EvaluationRunLog) plus the
new distributed `Trace`s, and normalizes each row into a common `TelemetryEvent` (source / latency /
tokens / cost / status / time). This is the "consume, don't duplicate" seam — a new module becomes
observable by adding one spec here, not by re-emitting its telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.observability.interfaces import TelemetryEvent


@dataclass
class SourceSpec:
    source: str
    model: type
    latency_field: str
    token_field: Optional[str] = None
    cost_field: Optional[str] = None
    status_field: Optional[str] = None
    op_field: Optional[str] = None
    status_default: str = "completed"


def _specs() -> List[SourceSpec]:
    from app.agents.models import AgentExecutionLog, AgentTaskLog
    from app.evaluation.models import EvaluationRunLog
    from app.graphreason.models import GraphReasoningLog
    from app.knowledge.models import GraphConstructionLog
    from app.memory.models import SemanticMemoryLog
    from app.mmretrieval.models import RetrievalLog
    from app.observability.models import Trace
    from app.orchestration.models import OrchestrationExecutionLog
    from app.reasoning.models import VerificationLog
    from app.tretrieval.models import TemporalSearchLog
    return [
        SourceSpec("trace", Trace, "total_ms", "token_usage", "cost_estimate", "status", "operation", "ok"),
        SourceSpec("retrieval", RetrievalLog, "total_ms", op_field="query"),
        SourceSpec("temporal_retrieval", TemporalSearchLog, "total_ms", op_field="query"),
        SourceSpec("memory_retrieval", SemanticMemoryLog, "total_ms", op_field="mode"),
        SourceSpec("graph_build", GraphConstructionLog, "processing_ms", status_field="status", op_field="scope"),
        SourceSpec("graph_reasoning", GraphReasoningLog, "total_ms", op_field="pipeline_version"),
        SourceSpec("agent_run", AgentExecutionLog, "total_ms", "token_usage", "cost_estimate", "status", "agent"),
        SourceSpec("agent_task", AgentTaskLog, "total_ms", "token_usage", "cost_estimate", "status", "task_type"),
        SourceSpec("orchestration", OrchestrationExecutionLog, "total_ms", "token_usage", "cost_estimate", "status", "workflow"),
        SourceSpec("verification", VerificationLog, "verification_ms", status_field="status", op_field="mode"),
        SourceSpec("evaluation", EvaluationRunLog, "duration_ms", "token_usage", "cost_estimate", "status", "pipeline"),
    ]


def _row_event(spec: SourceSpec, row) -> TelemetryEvent:
    created = getattr(row, "created_at", None)
    return TelemetryEvent(
        source=spec.source, id=getattr(row, "id", ""), workspace_id=getattr(row, "workspace_id", ""),
        operation=str(getattr(row, spec.op_field, "") or "") if spec.op_field else "",
        latency_ms=float(getattr(row, spec.latency_field, 0.0) or 0.0),
        tokens=int(getattr(row, spec.token_field, 0) or 0) if spec.token_field else 0,
        cost=float(getattr(row, spec.cost_field, 0.0) or 0.0) if spec.cost_field else 0.0,
        status=str(getattr(row, spec.status_field, spec.status_default) if spec.status_field else spec.status_default),
        created_at=created.isoformat() if created else None)


class TelemetryUnifier:
    def __init__(self, db: Session):
        self.db = db

    def events(self, workspace_id: str, owner_id: str, *, source: Optional[str] = None,
               per_source: int = 40, limit: int = 200) -> List[TelemetryEvent]:
        out: List[TelemetryEvent] = []
        for spec in _specs():
            if source and spec.source != source:
                continue
            try:
                stmt = select(spec.model).where(
                    spec.model.workspace_id == workspace_id, spec.model.owner_id == owner_id)
                stmt = stmt.order_by(desc(spec.model.created_at)).limit(per_source)
                for row in self.db.scalars(stmt):
                    out.append(_row_event(spec, row))
            except Exception:
                continue
        out.sort(key=lambda e: e.created_at or "", reverse=True)
        return out[:limit]

    def by_source_counts(self, workspace_id: str, owner_id: str) -> dict:
        from sqlalchemy import func
        counts = {}
        for spec in _specs():
            try:
                counts[spec.source] = int(self.db.scalar(select(func.count()).select_from(spec.model).where(
                    spec.model.workspace_id == workspace_id, spec.model.owner_id == owner_id)) or 0)
            except Exception:
                counts[spec.source] = 0
        return counts
