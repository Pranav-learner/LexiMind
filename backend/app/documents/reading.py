"""Reading-session persistence (Phase 3, Module 3: PDF Viewer).

Backs "restore previous session automatically" (per-user last page / scroll / zoom / rotation
for a document) and "recently viewed documents" (the reading history). One row per
(owner, document): the service upserts it on every progress ping.

Layered like the rest of the documents package: this file holds the repository (all SQL) and
the service (rules) for reading sessions; DTOs live in schemas.py; routes in reading_api.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.documents.models import Document, ReadingSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReadingSessionRepository:
    """The ONLY place that issues SQL for reading sessions."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, owner_id: str, document_id: str) -> Optional[ReadingSession]:
        return self.db.scalar(
            select(ReadingSession).where(
                ReadingSession.owner_id == owner_id,
                ReadingSession.document_id == document_id,
            )
        )

    def upsert(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        document_id: str,
        page: int,
        scroll_top: int,
        zoom: int,
        rotation: int,
    ) -> ReadingSession:
        rs = self.get(owner_id, document_id)
        if rs is None:
            rs = ReadingSession(
                owner_id=owner_id,
                workspace_id=workspace_id,
                document_id=document_id,
                page=page,
                scroll_top=scroll_top,
                zoom=zoom,
                rotation=rotation,
            )
            self.db.add(rs)
        else:
            rs.page = page
            rs.scroll_top = scroll_top
            rs.zoom = zoom
            rs.rotation = rotation
            rs.updated_at = _now()
        self.db.commit()
        self.db.refresh(rs)
        return rs

    def history(self, owner_id: str, workspace_id: str, *, limit: int = 20) -> List[Tuple[ReadingSession, Document]]:
        """Recent reading sessions joined with their (live) documents, newest first."""
        stmt = (
            select(ReadingSession, Document)
            .join(Document, Document.id == ReadingSession.document_id)
            .where(
                ReadingSession.owner_id == owner_id,
                ReadingSession.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            )
            .order_by(desc(ReadingSession.updated_at))
            .limit(limit)
        )
        return list(self.db.execute(stmt).all())


class ReadingService:
    """Reading-session rules. Ownership of the document is verified by the caller (route)."""

    def __init__(self, repo: ReadingSessionRepository):
        self.repo = repo

    def save_progress(
        self,
        owner_id: str,
        workspace_id: str,
        document_id: str,
        *,
        page: int,
        scroll_top: int = 0,
        zoom: int = 100,
        rotation: int = 0,
    ) -> ReadingSession:
        page = max(1, page)
        scroll_top = max(0, scroll_top)
        zoom = min(1000, max(10, zoom))
        rotation = rotation % 360
        return self.repo.upsert(
            owner_id=owner_id,
            workspace_id=workspace_id,
            document_id=document_id,
            page=page,
            scroll_top=scroll_top,
            zoom=zoom,
            rotation=rotation,
        )

    def get(self, owner_id: str, document_id: str) -> Optional[ReadingSession]:
        return self.repo.get(owner_id, document_id)

    def history(self, owner_id: str, workspace_id: str, *, limit: int = 20):
        return self.repo.history(owner_id, workspace_id, limit=min(max(1, limit), 100))
