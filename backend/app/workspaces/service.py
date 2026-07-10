"""Workspace business logic — the single place CRUD rules live.

Depends on a `WorkspaceRepository` (data) and the pure `validation` helpers. It owns the
rules the API and any future caller (agents, scripts) must not bypass:
- name/description/icon/color validation + normalization,
- duplicate-name prevention (case-insensitive, per owner, among live rows),
- soft-delete by default, hard-delete only on explicit request,
- archive/restore state transitions,
- counter maintenance for the denormalized per-type counts.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.workspaces import validation
from app.workspaces.errors import (
    DuplicateWorkspaceName,
    WorkspaceNotFound,
    WorkspaceStateError,
)
from app.workspaces.models import Workspace
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.schemas import ArchivedFilter, SortField, SortOrder


class WorkspaceService:
    def __init__(self, repo: WorkspaceRepository):
        self.repo = repo

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, workspace_id: str, owner_id: str) -> Workspace:
        ws = self.repo.get(workspace_id, owner_id)
        if ws is None:
            raise WorkspaceNotFound(workspace_id)
        return ws

    def _ensure_name_free(self, owner_id: str, name: str, *, exclude_id: Optional[str] = None) -> None:
        name_cf = validation.normalize_name_for_compare(name)
        if self.repo.name_exists(owner_id, name_cf, exclude_id=exclude_id):
            raise DuplicateWorkspaceName(name)

    # ------------------------------------------------------------------ commands
    def create(
        self,
        owner_id: str,
        *,
        name: str,
        description: str = "",
        icon: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Workspace:
        name = validation.validate_name(name)
        description = validation.validate_description(description)
        icon = validation.validate_icon(icon)
        color = validation.validate_color(color)
        self._ensure_name_free(owner_id, name)
        ws = Workspace(
            name=name, description=description, icon=icon, color=color, owner_id=owner_id
        )
        return self.repo.create(ws)

    def update(
        self,
        workspace_id: str,
        owner_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Workspace:
        ws = self._get_or_404(workspace_id, owner_id)
        if name is not None:
            new_name = validation.validate_name(name)
            self._ensure_name_free(owner_id, new_name, exclude_id=ws.id)
            ws.name = new_name
        if description is not None:
            ws.description = validation.validate_description(description)
        if icon is not None:
            ws.icon = validation.validate_icon(icon)
        if color is not None:
            ws.color = validation.validate_color(color)
        return self.repo.save(ws)

    def archive(self, workspace_id: str, owner_id: str) -> Workspace:
        ws = self._get_or_404(workspace_id, owner_id)
        if ws.is_archived:
            raise WorkspaceStateError("Workspace is already archived.")
        ws.is_archived = True
        return self.repo.save(ws)

    def restore(self, workspace_id: str, owner_id: str) -> Workspace:
        ws = self._get_or_404(workspace_id, owner_id)
        if not ws.is_archived:
            raise WorkspaceStateError("Workspace is not archived.")
        ws.is_archived = False
        return self.repo.save(ws)

    def delete(self, workspace_id: str, owner_id: str, *, permanent: bool = False) -> None:
        """Soft-delete by default; hard-delete only when explicitly requested."""
        ws = self._get_or_404(workspace_id, owner_id)
        if permanent:
            self.repo.hard_delete(ws)
        else:
            self.repo.soft_delete(ws)

    # ------------------------------------------------------------------ queries
    def get(self, workspace_id: str, owner_id: str) -> Workspace:
        return self._get_or_404(workspace_id, owner_id)

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
        page = max(1, page)
        page_size = min(max(1, page_size), 100)  # hard cap protects against huge pages
        return self.repo.list(
            owner_id,
            page=page,
            page_size=page_size,
            search=search,
            archived=archived,
            sort_by=sort_by,
            order=order,
        )

    # -------------------------------------------------------- counter maintenance
    def adjust_counter(self, workspace_id: str, owner_id: str, field: str, delta: int) -> Workspace:
        """Used by other modules (e.g. ingestion) to keep denormalized counts accurate."""
        ws = self._get_or_404(workspace_id, owner_id)
        return self.repo.adjust_counter(ws, field, delta)
