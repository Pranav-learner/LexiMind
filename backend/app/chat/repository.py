"""Chat data-access layer. The ONLY place that issues SQL for chat entities.

Conversations are owner + workspace scoped and soft-delete aware. Message/citation reads are
batched to avoid N+1 (list messages, then load all their citations in one query and group in
Python).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.chat.models import Conversation, Message, MessageCitation
from app.chat.schemas import ArchivedFilter, PinnedFilter, SortField, SortOrder


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ reads
    def get(self, conversation_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Conversation]:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.owner_id == owner_id
        )
        if not include_deleted:
            stmt = stmt.where(Conversation.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        archived: ArchivedFilter = ArchivedFilter.active,
        pinned: PinnedFilter = PinnedFilter.any,
        sort_by: SortField = SortField.last_message_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Conversation], int]:
        conditions = [
            Conversation.owner_id == owner_id,
            Conversation.workspace_id == workspace_id,
            Conversation.deleted_at.is_(None),
        ]
        if archived == ArchivedFilter.active:
            conditions.append(Conversation.is_archived.is_(False))
        elif archived == ArchivedFilter.archived:
            conditions.append(Conversation.is_archived.is_(True))
        if pinned == PinnedFilter.pinned:
            conditions.append(Conversation.is_pinned.is_(True))
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Conversation.title).like(like),
                    func.lower(Conversation.description).like(like),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(Conversation).where(*conditions)) or 0

        column = getattr(Conversation, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (
            select(Conversation)
            .where(*conditions)
            # Pinned conversations always float to the top, then the chosen sort, then a stable id.
            .order_by(desc(Conversation.is_pinned), direction(column), desc(Conversation.id))
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    def search(self, owner_id: str, workspace_id: str, query: str, *, limit: int = 20) -> List[Conversation]:
        """Search conversations by title/description OR message content OR citation text.

        Returns distinct conversations, most-recent first. This is the broad "find that chat"
        search (Step 12); the list endpoint's `search` param is the cheaper title/description one.
        """
        like = f"%{query.strip().lower()}%"
        base = [
            Conversation.owner_id == owner_id,
            Conversation.workspace_id == workspace_id,
            Conversation.deleted_at.is_(None),
        ]
        msg_ids = select(Message.conversation_id).where(func.lower(Message.content).like(like))
        cit_msg = (
            select(Message.conversation_id)
            .join(MessageCitation, MessageCitation.message_id == Message.id)
            .where(func.lower(MessageCitation.citation_text).like(like))
        )
        stmt = (
            select(Conversation)
            .where(
                *base,
                or_(
                    func.lower(Conversation.title).like(like),
                    func.lower(Conversation.description).like(like),
                    Conversation.id.in_(msg_ids),
                    Conversation.id.in_(cit_msg),
                ),
            )
            .order_by(desc(Conversation.last_message_at), desc(Conversation.id))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    # ------------------------------------------------------------------ writes
    def create(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def save(self, conversation: Conversation) -> Conversation:
        conversation.updated_at = _now()
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = _now()
        self.db.commit()

    def hard_delete(self, conversation: Conversation) -> None:
        self.db.delete(conversation)
        self.db.commit()


class MessageRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, message: Message) -> Message:
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def add_citations(self, citations: List[MessageCitation]) -> List[MessageCitation]:
        if not citations:
            return []
        self.db.add_all(citations)
        self.db.commit()
        return citations

    def list(self, conversation_id: str, *, page: int = 1, page_size: int = 50) -> Tuple[List[Message], int]:
        conds = [Message.conversation_id == conversation_id]
        total = self.db.scalar(select(func.count()).select_from(Message).where(*conds)) or 0
        stmt = (
            select(Message)
            .where(*conds)
            .order_by(asc(Message.created_at), asc(Message.id))
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    def recent(self, conversation_id: str, *, limit: int = 40) -> List[Message]:
        """Most recent messages (chronological order) for building conversation memory."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(limit)
        )
        rows = list(self.db.scalars(stmt))
        rows.reverse()
        return rows

    def citations_for(self, message_ids: List[str]) -> Dict[str, List[MessageCitation]]:
        """Batch-load citations for many messages (avoids N+1)."""
        if not message_ids:
            return {}
        stmt = select(MessageCitation).where(MessageCitation.message_id.in_(message_ids))
        grouped: Dict[str, List[MessageCitation]] = defaultdict(list)
        for c in self.db.scalars(stmt):
            grouped[c.message_id].append(c)
        return grouped

    def delete_for_conversation(self, conversation_id: str) -> None:
        """Hard-delete all messages + their citations for a conversation."""
        msg_ids = list(self.db.scalars(
            select(Message.id).where(Message.conversation_id == conversation_id)
        ))
        if msg_ids:
            self.db.query(MessageCitation).filter(MessageCitation.message_id.in_(msg_ids)).delete(
                synchronize_session=False
            )
            self.db.query(Message).filter(Message.conversation_id == conversation_id).delete(
                synchronize_session=False
            )
            self.db.commit()
