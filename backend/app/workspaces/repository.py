"""Workspace data-access layer. The ONLY place that issues SQL for workspaces.

Every query is scoped to `owner_id` and, unless explicitly stated, excludes soft-deleted
rows (`deleted_at IS NULL`). Listing is done in a single query with SQL-side pagination,
sorting, search, and archived filtering — no N+1, no in-memory scans of the full table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.workspaces.models import COUNTER_FIELDS, Workspace
from app.workspaces.schemas import ArchivedFilter, SortField, SortOrder


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ reads
    def get(self, workspace_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Workspace]:
        stmt = select(Workspace).where(
            Workspace.id == workspace_id, Workspace.owner_id == owner_id
        )
        if not include_deleted:
            stmt = stmt.where(Workspace.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def name_exists(self, owner_id: str, name_cf: str, *, exclude_id: Optional[str] = None) -> bool:
        """Case-insensitive duplicate check among the owner's live (non-deleted) rows."""
        stmt = select(Workspace.id).where(
            Workspace.owner_id == owner_id,
            Workspace.deleted_at.is_(None),
            func.lower(Workspace.name) == name_cf,
        )
        if exclude_id:
            stmt = stmt.where(Workspace.id != exclude_id)
        return self.db.scalar(stmt) is not None

    def list(
        self,
        owner_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        archived: ArchivedFilter = ArchivedFilter.active,
        sort_by: SortField = SortField.updated_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Workspace], int]:
        """Return (page_items, total_count) in two cheap queries (count + windowed select)."""
        conditions = [Workspace.owner_id == owner_id, Workspace.deleted_at.is_(None)]
        if archived == ArchivedFilter.active:
            conditions.append(Workspace.is_archived.is_(False))
        elif archived == ArchivedFilter.archived:
            conditions.append(Workspace.is_archived.is_(True))
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Workspace.name).like(like),
                    func.lower(Workspace.description).like(like),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(Workspace).where(*conditions)) or 0

        column = getattr(Workspace, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (
            select(Workspace)
            .where(*conditions)
            .order_by(direction(column), desc(Workspace.id))  # id tiebreaker = stable paging
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    # ------------------------------------------------------------------ writes
    def create(self, workspace: Workspace) -> Workspace:
        self.db.add(workspace)
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def save(self, workspace: Workspace) -> Workspace:
        workspace.updated_at = _now()
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def soft_delete(self, workspace: Workspace) -> None:
        workspace.deleted_at = _now()
        self.db.commit()

    def hard_delete(self, workspace: Workspace) -> None:
        self.db.delete(workspace)
        self.db.commit()

    def adjust_counter(self, workspace: Workspace, field: str, delta: int) -> Workspace:
        """Atomically nudge one denormalized counter (never below zero)."""
        if field not in COUNTER_FIELDS:
            raise ValueError(f"Unknown counter field: {field}")
        current = getattr(workspace, field) or 0
        setattr(workspace, field, max(0, current + delta))
        workspace.updated_at = _now()
        self.db.commit()
        self.db.refresh(workspace)
        return workspace
