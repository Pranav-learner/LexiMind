"""Citation indexer — builds the unified citation-intelligence index from the source modules.

This is the ONLY place that reads the four per-module citation tables (message/summary/note/
flashcard) and materializes the derived `Citation` / `CitationReference` / `KnowledgeReference`
rows. It is a deterministic, idempotent, per-workspace FULL REBUILD (delete + rebuild), which keeps
the index perfectly consistent with the modules that own the data. A cheap count-based staleness
check (`source_reference_count`) lets the service skip rebuilds when nothing changed.

Nothing here changes retrieval behaviour — it only re-exposes citation metadata already persisted.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Dict, List

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.citations.models import Citation, CitationReference, KnowledgeReference

# Guards against quadratic blow-up when materializing co-occurrence edges.
_MAX_CHUNKS_PER_ARTIFACT = 40
_MAX_SAME_DOC_EDGES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _group_key(document_id, chunk_id, page_number, source_row_id) -> str:
    if chunk_id:
        return f"chunk:{chunk_id}"
    if document_id:
        return f"doc:{document_id}:p{page_number if page_number is not None else '?'}"
    return f"src:{source_row_id}"


class CitationIndexer:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ staleness
    def source_reference_count(self, workspace_id: str) -> int:
        """Total live source-citation rows for the workspace (cheap staleness signal)."""
        from app.chat.models import Conversation, Message, MessageCitation
        from app.flashcards.models import Flashcard, FlashcardCitation
        from app.notes.models import Note, NoteCitation
        from app.summaries.models import Summary, SummaryCitation, SummarySection

        n = 0
        n += self.db.scalar(
            select(func.count()).select_from(MessageCitation)
            .join(Message, Message.id == MessageCitation.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(MessageCitation.workspace_id == workspace_id, Conversation.deleted_at.is_(None))
        ) or 0
        n += self.db.scalar(
            select(func.count()).select_from(SummaryCitation)
            .join(SummarySection, SummarySection.id == SummaryCitation.summary_section_id)
            .join(Summary, Summary.id == SummarySection.summary_id)
            .where(SummaryCitation.workspace_id == workspace_id, Summary.deleted_at.is_(None))
        ) or 0
        n += self.db.scalar(
            select(func.count()).select_from(NoteCitation)
            .join(Note, Note.id == NoteCitation.note_id)
            .where(NoteCitation.workspace_id == workspace_id, Note.deleted_at.is_(None))
        ) or 0
        n += self.db.scalar(
            select(func.count()).select_from(FlashcardCitation)
            .join(Flashcard, Flashcard.id == FlashcardCitation.flashcard_id)
            .where(FlashcardCitation.workspace_id == workspace_id, Flashcard.deleted_at.is_(None))
        ) or 0
        return int(n)

    def indexed_reference_count(self, workspace_id: str) -> int:
        return int(self.db.scalar(
            select(func.count()).select_from(CitationReference).where(CitationReference.workspace_id == workspace_id)
        ) or 0)

    # ------------------------------------------------------------------ collect
    def _collect(self, workspace_id: str) -> List[dict]:
        """Read all live source citations for a workspace into a uniform shape."""
        from app.chat.models import Conversation, Message, MessageCitation
        from app.flashcards.models import Flashcard, FlashcardCitation
        from app.notes.models import Note, NoteCitation
        from app.summaries.models import Summary, SummaryCitation, SummarySection

        rows: List[dict] = []

        # chat messages
        for mc, conv in self.db.execute(
            select(MessageCitation, Conversation)
            .join(Message, Message.id == MessageCitation.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(MessageCitation.workspace_id == workspace_id, Conversation.deleted_at.is_(None))
        ).all():
            rows.append(self._row("message", mc, artifact_id=mc.message_id, parent_id=conv.id,
                                  child_id=mc.message_id, title=conv.title, typed={"message_id": mc.message_id}))

        # summaries
        for sc, summ, sec in self.db.execute(
            select(SummaryCitation, Summary, SummarySection)
            .join(SummarySection, SummarySection.id == SummaryCitation.summary_section_id)
            .join(Summary, Summary.id == SummarySection.summary_id)
            .where(SummaryCitation.workspace_id == workspace_id, Summary.deleted_at.is_(None))
        ).all():
            rows.append(self._row("summary", sc, artifact_id=summ.id, parent_id=summ.id,
                                  child_id=sec.id, title=summ.title, typed={"summary_id": summ.id}))

        # notes
        for nc, note in self.db.execute(
            select(NoteCitation, Note)
            .join(Note, Note.id == NoteCitation.note_id)
            .where(NoteCitation.workspace_id == workspace_id, Note.deleted_at.is_(None))
        ).all():
            rows.append(self._row("note", nc, artifact_id=note.id, parent_id=note.id,
                                  child_id=nc.note_section_id, title=note.title, typed={"note_id": note.id}))

        # flashcards
        for fc, card in self.db.execute(
            select(FlashcardCitation, Flashcard)
            .join(Flashcard, Flashcard.id == FlashcardCitation.flashcard_id)
            .where(FlashcardCitation.workspace_id == workspace_id, Flashcard.deleted_at.is_(None))
        ).all():
            rows.append(self._row("flashcard", fc, artifact_id=card.id, parent_id=card.deck_id,
                                  child_id=card.id, title=(card.front or "")[:400], typed={"flashcard_id": card.id}))

        return rows

    @staticmethod
    def _row(ref_type, src, *, artifact_id, parent_id, child_id, title, typed) -> dict:
        return {
            "ref_type": ref_type,
            "source_row_id": src.id,
            "document_id": src.document_id,
            "chunk_id": src.chunk_id,
            "page_number": src.page_number,
            "citation_text": src.citation_text or "",
            "confidence": src.confidence,
            "artifact_key": f"{ref_type}:{artifact_id}",
            "parent_id": parent_id,
            "child_id": child_id,
            "title": title or "",
            "typed": typed,
            "group_key": _group_key(src.document_id, src.chunk_id, src.page_number, src.id),
        }

    # ------------------------------------------------------------------ rebuild
    def rebuild(self, workspace_id: str, owner_id: str) -> int:
        """Delete + rebuild the workspace's citation index. Returns the citation count."""
        self.db.execute(delete(KnowledgeReference).where(KnowledgeReference.workspace_id == workspace_id))
        self.db.execute(delete(CitationReference).where(CitationReference.workspace_id == workspace_id))
        self.db.execute(delete(Citation).where(Citation.workspace_id == workspace_id))
        self.db.flush()

        rows = self._collect(workspace_id)
        if not rows:
            self.db.commit()
            return 0

        # 1) Group rows into unified citations by natural key.
        groups: Dict[str, List[dict]] = defaultdict(list)
        for r in rows:
            groups[r["group_key"]].append(r)

        citation_by_group: Dict[str, Citation] = {}
        for gkey, grp in groups.items():
            best_text = max((g["citation_text"] for g in grp), key=len, default="")
            confs = [g["confidence"] for g in grp if g["confidence"] is not None]
            page = next((g["page_number"] for g in grp if g["page_number"] is not None), None)
            doc = next((g["document_id"] for g in grp if g["document_id"]), None)
            chunk = next((g["chunk_id"] for g in grp if g["chunk_id"]), None)
            conf = max(confs) if confs else None
            cit = Citation(
                workspace_id=workspace_id, owner_id=owner_id, document_id=doc, chunk_id=chunk,
                group_key=gkey, page_number=page, citation_text=best_text[:4000],
                confidence=conf, evidence_score=conf, reference_count=len(grp),
            )
            self.db.add(cit)
            citation_by_group[gkey] = cit
        self.db.flush()  # assign citation ids

        # 2) References.
        for r in rows:
            cit = citation_by_group[r["group_key"]]
            self.db.add(CitationReference(
                citation_id=cit.id, workspace_id=workspace_id, reference_type=r["ref_type"],
                message_id=r["typed"].get("message_id"), summary_id=r["typed"].get("summary_id"),
                note_id=r["typed"].get("note_id"), flashcard_id=r["typed"].get("flashcard_id"),
                ref_parent_id=r["parent_id"], ref_child_id=r["child_id"], ref_title=r["title"][:400],
                source_row_id=r["source_row_id"],
            ))

        # 3) Knowledge edges — co-occurrence within an artifact.
        by_artifact: Dict[str, set] = defaultdict(set)
        for r in rows:
            by_artifact[r["artifact_key"]].add(r["group_key"])
        pair_strength: Dict[tuple, int] = defaultdict(int)
        for _artifact, gkeys in by_artifact.items():
            gk = [g for g in gkeys]
            if len(gk) < 2 or len(gk) > _MAX_CHUNKS_PER_ARTIFACT:
                continue
            for a, b in combinations(sorted(gk), 2):
                pair_strength[(a, b)] += 1
        self._add_edges(workspace_id, pair_strength, citation_by_group, "co_reference")

        # 4) Knowledge edges — same document neighbours (bounded).
        by_doc: Dict[str, List[str]] = defaultdict(list)
        for gkey, cit in citation_by_group.items():
            if cit.document_id:
                by_doc[cit.document_id].append(gkey)
        same_doc_pairs: Dict[tuple, int] = {}
        for _doc, gkeys in by_doc.items():
            for a in gkeys:
                neighbours = [b for b in gkeys if b != a][:_MAX_SAME_DOC_EDGES]
                for b in neighbours:
                    key = tuple(sorted((a, b)))
                    same_doc_pairs.setdefault(key, 1)
        # Only add same_document edges for pairs NOT already co_reference (avoid redundancy).
        for (a, b) in same_doc_pairs:
            if (a, b) not in pair_strength:
                self._edge(workspace_id, citation_by_group, a, b, "same_document", 1.0)
                self._edge(workspace_id, citation_by_group, b, a, "same_document", 1.0)

        self.db.commit()
        return len(citation_by_group)

    def _add_edges(self, workspace_id, pair_strength, cmap, relationship):
        for (a, b), strength in pair_strength.items():
            self._edge(workspace_id, cmap, a, b, relationship, float(strength))
            self._edge(workspace_id, cmap, b, a, relationship, float(strength))

    def _edge(self, workspace_id, cmap, from_key, to_key, relationship, strength):
        src, dst = cmap.get(from_key), cmap.get(to_key)
        if src is None or dst is None:
            return
        self.db.add(KnowledgeReference(
            citation_id=src.id, workspace_id=workspace_id,
            related_chunk_id=dst.chunk_id, related_document_id=dst.document_id,
            related_citation_id=dst.id, relationship=relationship, strength=strength,
        ))
