"""Knowledge Graph ORM (Phase 7, Module 1) — the semantic layer's persistent store.

Three tables, workspace-scoped + soft-delete (merge/restore) — deliberately storage-agnostic in shape
(plain rows + JSON provenance) so the SAME model maps onto Neo4j/AGE/Memgraph later behind the
`GraphStore` interface:

- `GraphEntity`        — a canonical node (people/orgs/tech/concepts/…) with aliases + provenance + version.
- `GraphRelationship`  — a typed, directed, weighted edge with supporting evidence + version.
- `GraphConstructionLog` — one telemetry row per build (Step 12 observability; never business data).

Evidence/provenance is denormalized into JSON (the project's citation-style pattern) so a node/edge is
self-describing without joins. Versioning is a monotonic `version` int + soft-delete + the construction
log as history (time-travel queries are a Module-2/future concern).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # ent_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, default="concept")
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)   # dedup key (lowercased/stripped)
    aliases: Mapped[list | None] = mapped_column(JSON, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)       # cached edge count
    source_refs: Mapped[list | None] = mapped_column(JSON, default=None)          # [{document_id,chunk_id,source_type}]

    # lifecycle / versioning
    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False, default="active")
    # active | merged | deleted
    merged_into: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_gent_ws_norm", "workspace_id", "normalized_name"),
        Index("ix_gent_ws_type", "workspace_id", "entity_type"),
        Index("ix_gent_ws_status", "workspace_id", "status"),
    )


class GraphRelationship(Base):
    __tablename__ = "graph_relationships"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # rel_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    source_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    target_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    rel_type: Mapped[str] = mapped_column(String(40), nullable=False, default="related_to")
    directed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[list | None] = mapped_column(JSON, default=None)   # [{text, document_id, chunk_id}]

    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_grel_ws_src", "workspace_id", "source_id"),
        Index("ix_grel_ws_tgt", "workspace_id", "target_id"),
        Index("ix_grel_ws_type", "workspace_id", "rel_type"),
    )


class GraphConstructionLog(Base):
    __tablename__ = "graph_construction_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # gcl_…
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="document")   # document | workspace | agent

    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="completed")
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False, default="graph-v1")

    sources_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_merged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationships_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationships_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates_merged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    processing_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    report: Mapped[dict | None] = mapped_column(JSON, default=None)   # validation report + confidence dist

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_gcl_ws_created", "workspace_id", "created_at"),
    )
