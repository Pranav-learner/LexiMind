"""Analytics ORM — Phase 3, Module 9: Knowledge Dashboard & Analytics Platform.

ONE new table: `AnalyticsSnapshot` — a per-(workspace, section) cache of a computed dashboard
widget. Like the citation index (Module 8), this module owns no primary data; it aggregates the
other modules' rows. Aggregation can be expensive, so each widget's JSON payload is cached and only
recomputed when a cheap COUNT-based `signature` changes (data mutated) or a short TTL lapses (for
time-relative metrics like "days since review"). This keeps the dashboard fast on large workspaces
without a background job.

Future-proofing: `section` is an open string keyed by the widget registry, so new modules can add
widgets (and thus new cached sections) with zero schema change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    # Naive UTC to match SQLite's tz-stripped reads (project-wide convention since Module 7).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _snap_id() -> str:
    return f"snap_{uuid.uuid4().hex[:16]}"


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_snap_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    section: Mapped[str] = mapped_column(String(40), nullable=False)     # widget key
    signature: Mapped[str] = mapped_column(String(200), nullable=False)  # cheap data fingerprint
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "section", name="uq_snapshot_ws_section"),
        Index("ix_snapshots_ws", "workspace_id"),
    )
