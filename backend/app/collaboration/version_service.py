"""Version history snapshots for editable artifacts.

Takes a JSON snapshot of the artifact state on each significant save. Append-only log
that powers future diff, restore, and branching features.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.collaboration.errors import VersionNotFound
from app.collaboration.models import VersionSnapshot
from app.collaboration.version_repository import VersionRepository


class VersionService:

    def __init__(self, repo: VersionRepository | None = None):
        self.repo = repo or VersionRepository()

    def snapshot(
        self,
        db: Session,
        *,
        workspace_id: str,
        actor_id: str,
        target_type: str,
        target_id: str,
        snapshot: dict,
        change_summary: str = "",
    ) -> VersionSnapshot:
        """Create a new version snapshot of an artifact."""
        version_number = self.repo.get_latest_version_number(db, target_type, target_id) + 1

        # Compute size.
        snapshot_bytes = json.dumps(snapshot, default=str).encode("utf-8")
        snapshot_size = len(snapshot_bytes)

        vs = VersionSnapshot(
            workspace_id=workspace_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            version_number=version_number,
            snapshot=snapshot,
            change_summary=change_summary,
            snapshot_size=snapshot_size,
        )
        self.repo.create(db, vs)
        db.commit()
        return vs

    def get(self, db: Session, version_id: str) -> VersionSnapshot:
        vs = self.repo.get_by_id(db, version_id)
        if vs is None:
            raise VersionNotFound(version_id)
        return vs

    def list_for_target(
        self,
        db: Session,
        target_type: str,
        target_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VersionSnapshot]:
        return self.repo.list_for_target(
            db, target_type, target_id, limit=limit, offset=offset
        )

    def list_for_workspace(
        self,
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VersionSnapshot]:
        return self.repo.list_for_workspace(db, workspace_id, limit=limit, offset=offset)
