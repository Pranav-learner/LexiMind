"""Data-access layer for the VersionSnapshot table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.collaboration.models import VersionSnapshot


class VersionRepository:

    @staticmethod
    def create(db: Session, snapshot: VersionSnapshot) -> VersionSnapshot:
        db.add(snapshot)
        db.flush()
        return snapshot

    @staticmethod
    def get_by_id(db: Session, version_id: str) -> Optional[VersionSnapshot]:
        return db.scalar(
            select(VersionSnapshot).where(VersionSnapshot.id == version_id)
        )

    @staticmethod
    def list_for_target(
        db: Session,
        target_type: str,
        target_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VersionSnapshot]:
        return list(
            db.scalars(
                select(VersionSnapshot)
                .where(
                    VersionSnapshot.target_type == target_type,
                    VersionSnapshot.target_id == target_id,
                )
                .order_by(VersionSnapshot.version_number.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def list_for_workspace(
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VersionSnapshot]:
        return list(
            db.scalars(
                select(VersionSnapshot)
                .where(VersionSnapshot.workspace_id == workspace_id)
                .order_by(VersionSnapshot.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def get_latest_version_number(
        db: Session,
        target_type: str,
        target_id: str,
    ) -> int:
        result = db.scalar(
            select(func.max(VersionSnapshot.version_number)).where(
                VersionSnapshot.target_type == target_type,
                VersionSnapshot.target_id == target_id,
            )
        )
        return result or 0

    @staticmethod
    def count_for_target(
        db: Session,
        target_type: str,
        target_id: str,
    ) -> int:
        return db.scalar(
            select(func.count()).select_from(VersionSnapshot).where(
                VersionSnapshot.target_type == target_type,
                VersionSnapshot.target_id == target_id,
            )
        ) or 0
