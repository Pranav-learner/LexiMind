"""Note business logic — lifecycle, autosave, tags, conversions, and the generation pipeline.

Every creation path (blank, from-document AI, from-summary, from-chat, from-selection) funnels
through this one service and the one `Note` model. AI generation is asynchronous exactly like
summaries: `create_generated` enqueues a `queued` note; a background runner later calls
`generate_now`, which consumes the injected engine's events, persists sections + citations,
assembles the editable `content`, tracks progress, and honors cancellation. The engine (not this
service) does retrieval/context/LLM — reused, never forked.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.notes import validation
from app.notes.errors import (
    DuplicateTagName,
    NoteConflict,
    NoteNotFound,
    NoteStateError,
    SourceNotFound,
    TagNotFound,
)
from app.notes.models import Note, NoteCitation, NoteSection, Tag
from app.notes.repository import NoteRepository
from app.notes.schemas import (
    ArchivedFilter,
    PinnedFilter,
    SortField,
    SortOrder,
    StatusFilter,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NoteService:
    def __init__(self, repo: NoteRepository, workspace_service=None):
        self.repo = repo
        self.workspace_service = workspace_service

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, note_id: str, owner_id: str) -> Note:
        n = self.repo.get(note_id, owner_id)
        if n is None:
            raise NoteNotFound(note_id)
        return n

    def _get_tag_or_404(self, tag_id: str, owner_id: str) -> Tag:
        t = self.repo.get_tag(tag_id, owner_id)
        if t is None:
            raise TagNotFound(tag_id)
        return t

    def _bump_ws(self, workspace_id: str, owner_id: str, delta: int) -> None:
        if self.workspace_service is None:
            return
        try:
            self.workspace_service.adjust_counter(workspace_id, owner_id, "note_count", delta)
        except Exception:
            pass

    def _apply_metrics(self, note: Note) -> None:
        wc = validation.word_count(note.content)
        note.word_count = wc
        note.reading_time = validation.reading_minutes(wc)

    @staticmethod
    def _assemble_content(sections: List[Dict[str, Any]]) -> str:
        """Turn generated sections into one editable Markdown body."""
        blocks: List[str] = []
        for sec in sections:
            heading = (sec.get("heading") or "").strip()
            body = (sec.get("content") or "").strip()
            if heading:
                blocks.append(f"## {heading}\n\n{body}" if body else f"## {heading}")
            elif body:
                blocks.append(body)
        return "\n\n".join(blocks).strip() + ("\n" if blocks else "")

    # ------------------------------------------------------------------ manual creation
    def create(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        source: Optional[str] = None,
        document_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
    ) -> Note:
        """Blank / selection / paste-from-chat creation — no AI, born `ready`."""
        src = (source or "blank").strip().lower()
        if src not in validation.SOURCES:
            src = "blank"
        content = validation.validate_content(content or "")
        note = Note(
            owner_id=owner_id,
            workspace_id=workspace_id,
            document_id=document_id,
            conversation_id=conversation_id,
            source=src,
            title=validation.validate_title(title, default=validation.default_note_title(None, source=src)),
            description=validation.validate_description(description),
            content=content,
            status="ready",
            stage="ready",
            progress=100,
            created_by="user",
        )
        self._apply_metrics(note)
        note = self.repo.create(note)
        if citations:
            self.repo.add_citations(note.id, workspace_id, self._citation_rows(citations))
            note.citation_count = len(citations)
            self.repo.save(note)
        if tags:
            self._safe_set_tags(note, tags)
        self._bump_ws(workspace_id, owner_id, +1)
        return note

    # ------------------------------------------------------------------ AI creation (async)
    def create_generated(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        note_type: str,
        scope: Optional[str] = None,
        document_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        title: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Note:
        note_type = validation.validate_note_type(note_type)
        scope = validation.validate_scope(scope, document_id=document_id, document_ids=document_ids)
        title = validation.validate_title(
            title, default=validation.default_note_title(note_type, source="document", subject=subject)
        )
        note = Note(
            owner_id=owner_id,
            workspace_id=workspace_id,
            document_id=document_id if scope == "document" else None,
            document_ids=document_ids if scope == "multi" else None,
            scope=scope,
            conversation_id=conversation_id,
            source="document",
            note_type=note_type,
            title=title,
            status="queued",
            stage="queued",
            progress=0,
            created_by="ai",
        )
        note = self.repo.create(note)
        self._bump_ws(workspace_id, owner_id, +1)
        return note

    # ------------------------------------------------------------------ conversions
    def convert_from_summary(self, owner_id: str, workspace_id: str, summary_id: str) -> Note:
        """Convert an existing AI Summary into an editable Note (sections + citations preserved)."""
        from app.summaries.repository import SummaryRepository  # local: avoid import cycle

        srepo = SummaryRepository(self.repo.db)
        summary = srepo.get(summary_id, owner_id)
        if summary is None or summary.workspace_id != workspace_id:
            raise SourceNotFound(f"Summary '{summary_id}' was not found.")
        sections = srepo.sections(summary.id)
        cmap = srepo.citations_for([s.id for s in sections])

        note = Note(
            owner_id=owner_id,
            workspace_id=workspace_id,
            document_id=summary.document_id,
            source="summary",
            note_type=None,
            title=validation.validate_title(summary.title, default="Notes from summary"),
            status="ready",
            stage="ready",
            progress=100,
            created_by="ai",
        )
        note = self.repo.create(note)
        section_dicts = [{"heading": s.heading, "content": s.content} for s in sections]
        for i, s in enumerate(sections, start=1):
            cits = [
                {"document_id": c.document_id, "chunk_id": c.chunk_id, "page_number": c.page_number,
                 "text": c.citation_text, "confidence": c.confidence}
                for c in cmap.get(s.id, [])
            ]
            self._persist_section(note, {"heading": s.heading, "order": i, "content": s.content, "citations": cits})
        note.content = self._assemble_content(section_dicts)
        note.section_count = len(sections)
        note.citation_count = sum(len(cmap.get(s.id, [])) for s in sections)
        note.status = "completed"
        self._apply_metrics(note)
        self.repo.save(note)
        self._bump_ws(workspace_id, owner_id, +1)
        return note

    def convert_from_message(self, owner_id: str, workspace_id: str, message_id: str) -> Note:
        """Save a chat assistant message (with its citations) as a Note."""
        from app.chat.models import Conversation, Message, MessageCitation  # local import
        from sqlalchemy import select

        db = self.repo.db
        msg = db.scalar(select(Message).where(Message.id == message_id))
        if msg is None:
            raise SourceNotFound(f"Message '{message_id}' was not found.")
        conv = db.scalar(select(Conversation).where(Conversation.id == msg.conversation_id))
        if conv is None or conv.owner_id != owner_id or conv.workspace_id != workspace_id:
            raise SourceNotFound(f"Message '{message_id}' was not found.")
        cits = list(db.scalars(select(MessageCitation).where(MessageCitation.message_id == message_id)))

        note = Note(
            owner_id=owner_id,
            workspace_id=workspace_id,
            conversation_id=conv.id,
            source="chat",
            title=validation.validate_title(conv.title, default="Notes from chat"),
            content=validation.validate_content(msg.content or ""),
            status="ready",
            stage="ready",
            progress=100,
            created_by="ai",
        )
        self._apply_metrics(note)
        note = self.repo.create(note)
        if cits:
            rows = [
                NoteCitation(
                    document_id=c.document_id, chunk_id=c.chunk_id, page_number=c.page_number,
                    citation_text=c.citation_text, confidence=c.confidence, workspace_id=workspace_id,
                )
                for c in cits
            ]
            self.repo.add_citations(note.id, workspace_id, rows)
            note.citation_count = len(rows)
            self.repo.save(note)
        self._bump_ws(workspace_id, owner_id, +1)
        return note

    # ------------------------------------------------------------------ the generation pipeline
    def generate_now(self, note_id: str, engine) -> Optional[Note]:
        """Run generation for a queued note (called by the background runner with a trusted id)."""
        note = self.repo.get_by_id_only(note_id)
        if note is None:
            return None
        if note.status == "cancelled":
            return note

        started = time.perf_counter()
        self.repo.clear_sections(note.id)
        note.status = "processing"
        note.stage = "retrieving"
        note.progress = 1
        note.error = None
        self.repo.save(note)

        total = 1
        done = 0
        section_dicts: List[Dict[str, Any]] = []
        try:
            for ev in engine.generate(note, self.repo.db):
                etype = ev.get("type")
                if etype == "plan":
                    total = max(1, int(ev.get("total", 1)))
                    if ev.get("model"):
                        note.model_name = ev["model"]
                    self.repo.save(note)
                elif etype == "section":
                    self.repo.db.refresh(note)
                    if note.status == "cancelled":
                        note.stage = "cancelled"
                        self.repo.save(note)
                        return note
                    self._persist_section(note, ev)
                    section_dicts.append({"heading": ev.get("heading", ""), "content": ev.get("content", "")})
                    done += 1
                    note.progress = min(99, int(done / total * 100))
                    note.stage = f"section {done}/{total}"
                    note.section_count = done
                    self.repo.save(note)
                elif etype == "final":
                    note.token_usage = int(ev.get("token_usage", 0))
        except Exception as e:  # failure recovery — persist error, keep partial sections
            note.status = "failed"
            note.stage = "failed"
            note.error = str(e)[:4000]
            self.repo.save(note)
            return note

        if note.status != "cancelled":
            note.content = self._assemble_content(section_dicts)
            note.citation_count = len(self.repo.citations(note.id))
            self._apply_metrics(note)
            note.status = "completed"
            note.stage = "completed"
            note.progress = 100
            note.generation_ms = int((time.perf_counter() - started) * 1000)
            self.repo.save(note)
        return note

    def _persist_section(self, note: Note, ev: Dict[str, Any]) -> None:
        cits = ev.get("citations", []) or []
        section = NoteSection(
            note_id=note.id,
            heading=(ev.get("heading") or "")[:300],
            order=int(ev.get("order", 0)),
            content=ev.get("content", "") or "",
            citation_count=len(cits),
        )
        rows = self._citation_rows(cits, workspace_id=note.workspace_id)
        self.repo.add_section(section, rows)

    def _citation_rows(self, cits: List[Dict[str, Any]], *, workspace_id: str = "") -> List[NoteCitation]:
        return [
            NoteCitation(
                document_id=c.get("document_id"),
                chunk_id=c.get("chunk_id"),
                page_number=c.get("page_number"),
                workspace_id=workspace_id,
                citation_text=(c.get("text") or c.get("citation_text") or c.get("source") or "")[:2000],
                confidence=c.get("confidence"),
            )
            for c in cits
        ]

    # ------------------------------------------------------------------ AI-assisted editing
    def assist(self, note_id: str, owner_id: str, engine, *, operation: str, selection: str,
               instruction: Optional[str] = None, ground: bool = True) -> str:
        """Transform a selection of note text with an AI operation (synchronous)."""
        note = self._get_or_404(note_id, owner_id)
        return engine.assist(
            note, self.repo.db, operation=operation, selection=selection,
            instruction=instruction, ground=ground,
        )

    # ------------------------------------------------------------------ autosave (content)
    def save_content(self, note_id: str, owner_id: str, *, content: str,
                     base_version: Optional[int] = None, title: Optional[str] = None) -> Note:
        note = self._get_or_404(note_id, owner_id)
        content = validation.validate_content(content)
        # Optimistic concurrency: reject a stale client so we never clobber a newer edit.
        if base_version is not None and base_version != note.version:
            raise NoteConflict(note.version, base_version)
        changed = content != note.content
        if title is not None:
            new_title = validation.validate_title(title, default=note.title)
            if new_title != note.title:
                note.title = new_title
                changed = True
        if not changed:
            return note  # avoid unnecessary writes (perf)
        note.content = content
        note.version += 1
        self._apply_metrics(note)
        # A user edit graduates an AI note to a normal editable note.
        if note.status not in ("queued", "processing"):
            note.status = note.status if note.status in ("ready",) else "ready"
            note.stage = "ready"
        return self.repo.save(note)

    # ------------------------------------------------------------------ metadata commands
    def update_meta(self, note_id: str, owner_id: str, **fields) -> Note:
        note = self._get_or_404(note_id, owner_id)
        if fields.get("title") is not None:
            note.title = validation.validate_title(fields["title"], default=note.title)
        if fields.get("description") is not None:
            note.description = validation.validate_description(fields["description"])
        for flag in ("is_pinned", "is_favorite", "is_archived"):
            if fields.get(flag) is not None:
                setattr(note, flag, bool(fields[flag]))
        return self.repo.save(note)

    def cancel(self, note_id: str, owner_id: str) -> Note:
        n = self._get_or_404(note_id, owner_id)
        if n.status not in ("queued", "processing"):
            raise NoteStateError(f"Cannot cancel a '{n.status}' note.")
        n.status = "cancelled"
        n.stage = "cancelled"
        return self.repo.save(n)

    def reset_for_regenerate(self, note_id: str, owner_id: str) -> Note:
        n = self._get_or_404(note_id, owner_id)
        if not n.note_type:
            raise NoteStateError("Only AI-generated notes can be regenerated.")
        self.repo.clear_sections(n.id)
        n.status = "queued"
        n.stage = "queued"
        n.progress = 0
        n.error = None
        n.section_count = 0
        n.version += 1
        return self.repo.save(n)

    def duplicate(self, note_id: str, owner_id: str) -> Note:
        src = self._get_or_404(note_id, owner_id)
        copy = self.repo.create(Note(
            owner_id=owner_id, workspace_id=src.workspace_id, document_id=src.document_id,
            conversation_id=src.conversation_id, source=src.source, note_type=src.note_type,
            title=validation.validate_title(f"{src.title} (copy)", default=src.title),
            description=src.description, content=src.content, editor_format=src.editor_format,
            status="ready", stage="ready", progress=100, created_by=src.created_by,
            word_count=src.word_count, reading_time=src.reading_time,
            section_count=src.section_count, parent_note_id=src.id,
        ))
        # Copy sections + section-linked citations.
        for sec in self.repo.sections(src.id):
            self.repo.add_section(
                NoteSection(note_id=copy.id, heading=sec.heading, order=sec.order,
                            content=sec.content, citation_count=sec.citation_count),
                [],
            )
        # Copy note-level citations (both section-linked and free-standing) as free-standing.
        src_cits = self.repo.citations(src.id)
        if src_cits:
            self.repo.add_citations(copy.id, copy.workspace_id, [
                NoteCitation(document_id=c.document_id, chunk_id=c.chunk_id, page_number=c.page_number,
                             citation_text=c.citation_text, confidence=c.confidence,
                             workspace_id=copy.workspace_id)
                for c in src_cits
            ])
            copy.citation_count = len(src_cits)
            self.repo.save(copy)
        self._bump_ws(copy.workspace_id, owner_id, +1)
        return copy

    def delete(self, note_id: str, owner_id: str, *, permanent: bool = False) -> None:
        n = self._get_or_404(note_id, owner_id)
        if permanent:
            self.repo.detach_all_tags(n.id)
            self.repo.hard_delete(n)
        else:
            self.repo.soft_delete(n)
        self._bump_ws(n.workspace_id, n.owner_id, -1)

    # ------------------------------------------------------------------ tags
    def _safe_set_tags(self, note: Note, tag_ids: List[str]) -> None:
        # Keep only tags the owner actually owns in this workspace.
        valid = [t.id for t in self.repo.list_tags(note.owner_id, note.workspace_id) if t.id in set(tag_ids)]
        self.repo.set_note_tags(note.id, valid)

    def set_note_tags(self, note_id: str, owner_id: str, tag_ids: List[str]) -> Note:
        note = self._get_or_404(note_id, owner_id)
        self._safe_set_tags(note, tag_ids)
        return self.repo.get(note_id, owner_id)  # refreshed

    def create_tag(self, owner_id: str, workspace_id: str, *, name: str, color: Optional[str] = None) -> Tag:
        name = validation.validate_tag_name(name)
        if self.repo.tag_name_exists(owner_id, workspace_id, validation.normalize_tag_for_compare(name)):
            raise DuplicateTagName(name)
        return self.repo.create_tag(Tag(
            owner_id=owner_id, workspace_id=workspace_id, name=name,
            color=validation.validate_color(color),
        ))

    def update_tag(self, tag_id: str, owner_id: str, *, name: Optional[str] = None, color: Optional[str] = None) -> Tag:
        tag = self._get_tag_or_404(tag_id, owner_id)
        if name is not None:
            new_name = validation.validate_tag_name(name)
            if self.repo.tag_name_exists(owner_id, tag.workspace_id, validation.normalize_tag_for_compare(new_name), exclude_id=tag.id):
                raise DuplicateTagName(new_name)
            tag.name = new_name
        if color is not None:
            tag.color = validation.validate_color(color, default=tag.color)
        return self.repo.save_tag(tag)

    def delete_tag(self, tag_id: str, owner_id: str) -> None:
        tag = self._get_tag_or_404(tag_id, owner_id)
        self.repo.delete_tag(tag)

    def list_tags(self, owner_id: str, workspace_id: str) -> List[Tag]:
        return self.repo.list_tags(owner_id, workspace_id)

    # ------------------------------------------------------------------ queries
    def get(self, note_id: str, owner_id: str) -> Note:
        return self._get_or_404(note_id, owner_id)

    def get_detail(self, note_id: str, owner_id: str, *, touch: bool = True):
        n = self._get_or_404(note_id, owner_id)
        if touch:
            self.repo.touch_opened(n)
        sections = self.repo.sections(n.id)
        citations = self.repo.citations(n.id)
        tags = self.repo.tags_for([n.id]).get(n.id, [])
        outline = validation.outline_from_markdown(n.content)
        return n, sections, citations, tags, outline

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        **filters,
    ) -> Tuple[List[Note], int, Dict[str, List[Tag]]]:
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        notes, total = self.repo.list(owner_id, workspace_id, page=page, page_size=page_size, **filters)
        tag_map = self.repo.tags_for([n.id for n in notes])
        return notes, total, tag_map
