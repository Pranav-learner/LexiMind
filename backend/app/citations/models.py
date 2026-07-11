"""Citation-intelligence ORM models — Phase 3, Module 8: Citation Intelligence & Knowledge Explorer.

Three NEW tables (created by `create_all`, no migration). Unlike every prior module, these tables
are a DERIVED INDEX, not a new source of truth. Modules 4–7 already persist citations in four
structurally-identical tables (`message_citations`, `summary_citations`, `note_citations`,
`flashcard_citations`). This module aggregates those into a unified, explorable index:

- `Citation`          — one deduped citation per distinct evidence chunk in a workspace, with the
                        best-known scores + a denormalized reference count.
- `CitationReference` — a polymorphic link recording every place a citation is used (a chat
                        message, a summary, a note, a flashcard), with denormalized labels + a
                        navigation target so the panel renders with no extra joins.
- `KnowledgeReference`— a chunk↔chunk relationship (co-occurrence "backlinks" and same-document
                        neighbours) — the seed of the future Knowledge Graph.

The index is rebuilt per-workspace by `indexer.py` from the source tables (idempotent full rebuild
guarded by a cheap count-based staleness check), so it is always consistent with the modules that
own the data. Nothing here changes retrieval behaviour; it only EXPOSES metadata already collected.

Future-proofing (columns present, features NOT implemented): graph relationships
(`KnowledgeReference.relationship`/`strength`, `related_citation_id`), multi-document + cross-
workspace references (`related_document_id`), richer retrieval provenance
(`retrieval_score`/`reranker_score` — nullable for citations created before those were captured).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    # Naive UTC: SQLite reads DateTime columns back without tzinfo, so keep our clock naive to
    # avoid aware-vs-naive comparison errors (same convention as the flashcards module).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cit_id() -> str:
    return f"cite_{uuid.uuid4().hex[:16]}"


def _ref_id() -> str:
    return f"cref_{uuid.uuid4().hex[:16]}"


def _kn_id() -> str:
    return f"know_{uuid.uuid4().hex[:16]}"


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_cit_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    document_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # vector id
    chunk_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    # Natural dedup key within a workspace: the chunk_id, or a synthetic `doc:{id}:p{page}` when a
    # source citation has no chunk_id. Unique per workspace.
    group_key: Mapped[str] = mapped_column(String(120), nullable=False)

    page_number: Mapped[int | None] = mapped_column(Integer, default=None)
    paragraph_number: Mapped[int | None] = mapped_column(Integer, default=None)  # not tracked yet
    citation_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Scores. `confidence`/`evidence_score` come from Phase-2 evidence ranking (persisted as
    # `confidence` on the source rows). retrieval/reranker scores are nullable — they were not
    # persisted historically; the schema is ready to capture them going forward.
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    retrieval_score: Mapped[float | None] = mapped_column(Float, default=None)
    reranker_score: Mapped[float | None] = mapped_column(Float, default=None)
    evidence_score: Mapped[float | None] = mapped_column(Float, default=None)

    reference_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "group_key", name="uq_citation_ws_group"),
        Index("ix_citations_ws_doc", "workspace_id", "document_id"),
    )


class CitationReference(Base):
    __tablename__ = "citation_references"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_ref_id)
    citation_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    reference_type: Mapped[str] = mapped_column(String(20), nullable=False)  # message|summary|note|flashcard

    # Typed foreign keys (per the module spec). Exactly one is set per row.
    message_id: Mapped[str | None] = mapped_column(String(40), default=None)
    summary_id: Mapped[str | None] = mapped_column(String(40), default=None)
    note_id: Mapped[str | None] = mapped_column(String(40), default=None)
    flashcard_id: Mapped[str | None] = mapped_column(String(40), default=None)

    # Denormalized navigation + display (no joins needed to render the panel).
    ref_parent_id: Mapped[str | None] = mapped_column(String(40), default=None)  # conversation/summary/note/deck id
    ref_child_id: Mapped[str | None] = mapped_column(String(40), default=None)   # message/section/card id
    ref_title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    source_row_id: Mapped[str] = mapped_column(String(40), nullable=False)       # original citation row id

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("citation_id", "reference_type", "source_row_id", name="uq_ref_unique"),
        Index("ix_refs_type", "workspace_id", "reference_type"),
    )


class KnowledgeReference(Base):
    __tablename__ = "knowledge_references"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_kn_id)
    citation_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    related_chunk_id: Mapped[str | None] = mapped_column(String(80), default=None)
    related_document_id: Mapped[str | None] = mapped_column(String(40), default=None)
    related_citation_id: Mapped[str | None] = mapped_column(String(40), default=None)  # if the neighbour is indexed too

    relationship: Mapped[str] = mapped_column(String(30), nullable=False, default="co_reference")  # co_reference|same_document
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("citation_id", "related_chunk_id", "relationship", name="uq_knowledge_edge"),
        Index("ix_knowledge_ws", "workspace_id", "citation_id"),
    )
