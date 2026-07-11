"""Analytics data access — the cache layer + the cheap data fingerprint.

Heavy cross-module aggregation lives in `aggregators.py` (the statistics/analytics engine); this
repository only manages the `AnalyticsSnapshot` cache and computes the COUNT-based `signature` that
drives cache invalidation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsSnapshot


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AnalyticsRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ cache
    def get_snapshot(self, workspace_id: str, section: str) -> Optional[AnalyticsSnapshot]:
        return self.db.scalar(
            select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.workspace_id == workspace_id, AnalyticsSnapshot.section == section
            )
        )

    def upsert_snapshot(self, workspace_id: str, owner_id: str, section: str, signature: str, payload: dict) -> AnalyticsSnapshot:
        snap = self.get_snapshot(workspace_id, section)
        if snap is None:
            snap = AnalyticsSnapshot(workspace_id=workspace_id, owner_id=owner_id, section=section,
                                     signature=signature, payload=payload, computed_at=_now())
            self.db.add(snap)
        else:
            snap.signature = signature
            snap.payload = payload
            snap.computed_at = _now()
        self.db.commit()
        self.db.refresh(snap)
        return snap

    def invalidate(self, workspace_id: str) -> None:
        for snap in self.db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.workspace_id == workspace_id)):
            self.db.delete(snap)
        self.db.commit()

    # ------------------------------------------------------------------ signature
    def signature(self, workspace_id: str) -> str:
        """A cheap fingerprint of the workspace's data. When it changes, caches are stale.

        Uses the workspace's denormalized counters plus a few COUNTs for tables that mutate without
        bumping a counter (messages, reviews, citation references). ~4 COUNTs — far cheaper than the
        full aggregation it guards.
        """
        from app.chat.models import Conversation, Message
        from app.citations.models import CitationReference
        from app.documents.models import Document
        from app.flashcards.models import FlashcardReview
        from app.notes.models import Note
        from app.summaries.models import Summary
        from app.workspaces.models import Workspace

        ws = self.db.get(Workspace, workspace_id)
        counters = (
            f"{ws.document_count}.{ws.chat_count}.{ws.note_count}.{ws.flashcard_count}.{ws.summary_count}"
            if ws else "0"
        )

        def count(model, *conds):
            return self.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0

        # Messages have no workspace_id column → count via their conversation.
        msgs = self.db.scalar(
            select(func.count()).select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.workspace_id == workspace_id)
        ) or 0
        reviews = count(FlashcardReview, FlashcardReview.workspace_id == workspace_id)
        crefs = count(CitationReference, CitationReference.workspace_id == workspace_id)
        docs = count(Document, Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        notes = count(Note, Note.workspace_id == workspace_id, Note.deleted_at.is_(None))
        summs = count(Summary, Summary.workspace_id == workspace_id, Summary.deleted_at.is_(None))
        return f"{counters}|m{msgs}|r{reviews}|c{crefs}|d{docs}|n{notes}|s{summs}"
