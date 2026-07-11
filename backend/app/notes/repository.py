"""Note data-access layer — the ONLY place that issues SQL for notes/tags.

Owner + workspace scoped, soft-delete aware. Section/citation/tag reads are batched to avoid
N+1. Tag <-> note wiring lives here too (association rows + denormalized counters).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import asc, delete, desc, func, select
from sqlalchemy.orm import Session

from app.notes.models import Note, NoteCitation, NoteSection, NoteTag, Tag
from app.notes.schemas import ArchivedFilter, PinnedFilter, SortField, SortOrder, StatusFilter


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NoteRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ note reads
    def get(self, note_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Note]:
        stmt = select(Note).where(Note.id == note_id, Note.owner_id == owner_id)
        if not include_deleted:
            stmt = stmt.where(Note.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_by_id_only(self, note_id: str) -> Optional[Note]:
        """Lookup by id without an owner (used by the background runner's own session)."""
        return self.db.scalar(select(Note).where(Note.id == note_id))

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        note_type: Optional[str] = None,
        source: Optional[str] = None,
        document_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        tag_id: Optional[str] = None,
        status: StatusFilter = StatusFilter.any,
        archived: ArchivedFilter = ArchivedFilter.active,
        pinned: PinnedFilter = PinnedFilter.any,
        sort_by: SortField = SortField.updated_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Note], int]:
        conds = [
            Note.owner_id == owner_id,
            Note.workspace_id == workspace_id,
            Note.deleted_at.is_(None),
        ]
        if archived == ArchivedFilter.active:
            conds.append(Note.is_archived.is_(False))
        elif archived == ArchivedFilter.archived:
            conds.append(Note.is_archived.is_(True))
        if pinned == PinnedFilter.pinned:
            conds.append(Note.is_pinned.is_(True))
        elif pinned == PinnedFilter.favorite:
            conds.append(Note.is_favorite.is_(True))
        if note_type:
            conds.append(Note.note_type == note_type)
        if source:
            conds.append(Note.source == source)
        if document_id:
            conds.append(Note.document_id == document_id)
        if conversation_id:
            conds.append(Note.conversation_id == conversation_id)
        if status != StatusFilter.any:
            conds.append(Note.status == status.value)
        if search:
            like = f"%{search.strip().lower()}%"
            # Title OR content match — content search is a simple LIKE (semantic search is future).
            conds.append(func.lower(Note.title).like(like) | func.lower(Note.content).like(like))
        if tag_id:
            tagged = select(NoteTag.note_id).where(NoteTag.tag_id == tag_id)
            conds.append(Note.id.in_(tagged))

        total = self.db.scalar(select(func.count()).select_from(Note).where(*conds)) or 0
        column = getattr(Note, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (
            select(Note)
            .where(*conds)
            # Pinned notes always float to the top of any sort.
            .order_by(desc(Note.is_pinned), direction(column), desc(Note.id))
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    def sections(self, note_id: str) -> List[NoteSection]:
        return list(self.db.scalars(
            select(NoteSection).where(NoteSection.note_id == note_id).order_by(asc(NoteSection.order))
        ))

    def citations(self, note_id: str) -> List[NoteCitation]:
        return list(self.db.scalars(
            select(NoteCitation).where(NoteCitation.note_id == note_id).order_by(asc(NoteCitation.created_at))
        ))

    # ------------------------------------------------------------------ note writes
    def create(self, note: Note) -> Note:
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return note

    def save(self, note: Note) -> Note:
        note.updated_at = _now()
        self.db.commit()
        self.db.refresh(note)
        return note

    def touch_opened(self, note: Note) -> None:
        """Stamp last_opened_at WITHOUT bumping updated_at (opening is not an edit)."""
        note.last_opened_at = _now()
        self.db.commit()

    def add_section(self, section: NoteSection, citations: List[NoteCitation]) -> NoteSection:
        """Persist a section + its citations, stamping section/note ids onto each citation."""
        self.db.add(section)
        self.db.flush()  # assigns section.id
        for c in citations:
            c.note_id = section.note_id
            c.note_section_id = section.id
        if citations:
            self.db.add_all(citations)
        self.db.commit()
        self.db.refresh(section)
        return section

    def add_citations(self, note_id: str, workspace_id: str, citations: List[NoteCitation]) -> None:
        """Attach free-standing citations to a note (manual/conversion paths, no section)."""
        for c in citations:
            c.note_id = note_id
            c.workspace_id = workspace_id
        if citations:
            self.db.add_all(citations)
            self.db.commit()

    def clear_sections(self, note_id: str) -> None:
        """Remove AI sections + their (section-linked) citations before a regenerate."""
        self.db.execute(
            delete(NoteCitation).where(
                NoteCitation.note_id == note_id, NoteCitation.note_section_id.is_not(None)
            )
        )
        self.db.execute(delete(NoteSection).where(NoteSection.note_id == note_id))
        self.db.commit()

    def soft_delete(self, note: Note) -> None:
        note.deleted_at = _now()
        self.db.commit()

    def hard_delete(self, note: Note) -> None:
        self.db.execute(delete(NoteCitation).where(NoteCitation.note_id == note.id))
        self.db.execute(delete(NoteSection).where(NoteSection.note_id == note.id))
        self.db.execute(delete(NoteTag).where(NoteTag.note_id == note.id))
        self.db.delete(note)
        self.db.commit()

    # ------------------------------------------------------------------ tags
    def get_tag(self, tag_id: str, owner_id: str) -> Optional[Tag]:
        return self.db.scalar(select(Tag).where(Tag.id == tag_id, Tag.owner_id == owner_id))

    def tag_name_exists(self, owner_id: str, workspace_id: str, name_cf: str, *, exclude_id: Optional[str] = None) -> bool:
        stmt = select(func.count()).select_from(Tag).where(
            Tag.owner_id == owner_id,
            Tag.workspace_id == workspace_id,
            func.lower(Tag.name) == name_cf,
        )
        if exclude_id:
            stmt = stmt.where(Tag.id != exclude_id)
        return (self.db.scalar(stmt) or 0) > 0

    def list_tags(self, owner_id: str, workspace_id: str) -> List[Tag]:
        return list(self.db.scalars(
            select(Tag).where(Tag.owner_id == owner_id, Tag.workspace_id == workspace_id).order_by(asc(func.lower(Tag.name)))
        ))

    def create_tag(self, tag: Tag) -> Tag:
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def save_tag(self, tag: Tag) -> Tag:
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def delete_tag(self, tag: Tag) -> None:
        self.db.execute(delete(NoteTag).where(NoteTag.tag_id == tag.id))
        self.db.delete(tag)
        self.db.commit()

    def tags_for(self, note_ids: List[str]) -> Dict[str, List[Tag]]:
        """Batched note_id -> [Tag] map (avoids N+1 across a list of notes)."""
        if not note_ids:
            return {}
        rows = self.db.execute(
            select(NoteTag.note_id, Tag)
            .join(Tag, Tag.id == NoteTag.tag_id)
            .where(NoteTag.note_id.in_(note_ids))
            .order_by(asc(func.lower(Tag.name)))
        ).all()
        grouped: Dict[str, List[Tag]] = defaultdict(list)
        for note_id, tag in rows:
            grouped[note_id].append(tag)
        return grouped

    def set_note_tags(self, note_id: str, tag_ids: List[str]) -> None:
        """Replace a note's tag set, keeping each tag's denormalized note_count accurate."""
        current = set(self.db.scalars(select(NoteTag.tag_id).where(NoteTag.note_id == note_id)))
        target = set(tag_ids)
        to_add = target - current
        to_remove = current - target
        for tid in to_remove:
            self.db.execute(delete(NoteTag).where(NoteTag.note_id == note_id, NoteTag.tag_id == tid))
            self._bump_tag_count(tid, -1)
        for tid in to_add:
            self.db.add(NoteTag(note_id=note_id, tag_id=tid))
            self._bump_tag_count(tid, +1)
        self.db.commit()

    def detach_all_tags(self, note_id: str) -> None:
        for tid in list(self.db.scalars(select(NoteTag.tag_id).where(NoteTag.note_id == note_id))):
            self._bump_tag_count(tid, -1)
        self.db.execute(delete(NoteTag).where(NoteTag.note_id == note_id))
        self.db.commit()

    def _bump_tag_count(self, tag_id: str, delta: int) -> None:
        tag = self.db.get(Tag, tag_id)
        if tag is not None:
            tag.note_count = max(0, (tag.note_count or 0) + delta)
