"""Analytics service — the caching orchestration layer.

Every widget is computed through `section(...)`, which returns the cached payload when the data
fingerprint (signature) is unchanged and the snapshot is within TTL, and recomputes + stores
otherwise. This keeps the dashboard fast on large workspaces without a background job and without
recomputing expensive aggregates on every request. `dashboard()` assembles the curated overview;
`insights()` composes recommendations from freshly-cached sections; `refresh()` busts the cache.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.analytics.aggregators import WIDGETS, AggContext
from app.analytics.errors import DocumentNotFound, UnknownSection
from app.analytics.insights import generate_insights
from app.analytics.repository import AnalyticsRepository

# Time-relative widgets (streaks, "days since") get a short TTL so they refresh even when the
# underlying rows don't change; pure count widgets rely on the signature and can live longer.
_DEFAULT_TTL = timedelta(seconds=300)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AnalyticsService:
    # The curated set of widgets shown on the main dashboard overview.
    OVERVIEW_SECTIONS = ("knowledge", "ai_usage", "learning", "retrieval", "charts", "activity")

    def __init__(self, repo: AnalyticsRepository):
        self.repo = repo
        self.db: Session = repo.db

    def _ctx(self, workspace_id: str, owner_id: str) -> AggContext:
        return AggContext(db=self.db, workspace_id=workspace_id, owner_id=owner_id, now=_now())

    # ------------------------------------------------------------------ one section (cached)
    def section(self, workspace_id: str, owner_id: str, key: str, *, force: bool = False,
                signature: Optional[str] = None) -> dict:
        if key not in WIDGETS:
            raise UnknownSection(key)
        sig = signature if signature is not None else self.repo.signature(workspace_id)
        if not force:
            snap = self.repo.get_snapshot(workspace_id, key)
            if snap and snap.signature == sig and (_now() - snap.computed_at) < _DEFAULT_TTL:
                return snap.payload
        payload = WIDGETS[key](self._ctx(workspace_id, owner_id))
        self.repo.upsert_snapshot(workspace_id, owner_id, key, sig, payload)
        return payload

    # ------------------------------------------------------------------ full dashboard
    def dashboard(self, workspace_id: str, owner_id: str, *, force: bool = False) -> Dict[str, dict]:
        sig = self.repo.signature(workspace_id)
        sections = {k: self.section(workspace_id, owner_id, k, force=force, signature=sig)
                    for k in self.OVERVIEW_SECTIONS}
        sections["insights"] = self.insights(workspace_id, owner_id, force=force, signature=sig)
        return sections

    # ------------------------------------------------------------------ insights (composed)
    def insights(self, workspace_id: str, owner_id: str, *, force: bool = False,
                 signature: Optional[str] = None) -> list:
        sig = signature if signature is not None else self.repo.signature(workspace_id)
        if not force:
            snap = self.repo.get_snapshot(workspace_id, "insights")
            if snap and snap.signature == sig and (_now() - snap.computed_at) < _DEFAULT_TTL:
                return snap.payload.get("items", [])
        knowledge = self.section(workspace_id, owner_id, "knowledge", signature=sig)
        ai_usage = self.section(workspace_id, owner_id, "ai_usage", signature=sig)
        learning = self.section(workspace_id, owner_id, "learning", signature=sig)
        documents = self.section(workspace_id, owner_id, "documents", signature=sig)
        items = generate_insights(self._ctx(workspace_id, owner_id), knowledge, ai_usage, learning, documents)
        self.repo.upsert_snapshot(workspace_id, owner_id, "insights", sig, {"items": items})
        return items

    # ------------------------------------------------------------------ documents
    def documents(self, workspace_id: str, owner_id: str, *, force: bool = False) -> list:
        return self.section(workspace_id, owner_id, "documents", force=force).get("items", [])

    def document(self, workspace_id: str, owner_id: str, document_id: str) -> dict:
        for row in self.documents(workspace_id, owner_id):
            if row["id"] == document_id:
                return row
        raise DocumentNotFound(document_id)

    # ------------------------------------------------------------------ refresh
    def refresh(self, workspace_id: str, owner_id: str) -> dict:
        self.repo.invalidate(workspace_id)
        return self.dashboard(workspace_id, owner_id, force=True)
