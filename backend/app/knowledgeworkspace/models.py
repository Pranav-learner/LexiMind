"""Knowledge Workspace observability ORM (Step 13) — one activity-event table.

`KnowledgeWorkspaceLog` records what a user (or agent) DID in the knowledge workspace — node/relationship
views, graph searches, navigation, expansions, graph chat, edits, timeline/analytics views. It is
telemetry only; the graph itself lives in the Module-1 tables. Mirrors the Phase-4/5 single-event
observability tables (RetrievalLog / MediaInteractionEvent); never duplicates the graph/reasoning logs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class KnowledgeWorkspaceLog(Base):
    __tablename__ = "knowledge_workspace_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # kw_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # node_view | relationship_view | graph_search | navigation | entity_expansion |
    # graph_chat | graph_edit | timeline_view | analytics_view
    activity_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)   # entity/rel id
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_kwlog_ws_created", "workspace_id", "created_at"),
        Index("ix_kwlog_ws_type", "workspace_id", "activity_type"),
    )
