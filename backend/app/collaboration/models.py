"""Phase 9 · Module 1 — Collaboration ORM models.

Eight NEW tables (created by ``create_all``, no migration — the schema is additive):

- ``Organization``         — top-level entity that groups workspaces and users.
- ``OrganizationMember``   — user ↔ organization membership with role (owner/admin/member).
- ``WorkspaceMember``      — user ↔ workspace membership with role (owner/editor/viewer).
- ``Invitation``           — email-based invitation to an organization or workspace.
- ``Comment``              — unified comment on ANY artifact (document, note, graph node,
                            AI response, media timeline, flashcard, summary, etc.).
- ``ActivityEvent``        — workspace activity feed entry (chronological, typed, actor-scoped).
- ``VersionSnapshot``      — version history for editable artifacts (notes, documents, graph,
                            summaries, flashcards, workspace metadata, comments, research reports).
- ``CollaborationLog``     — observability telemetry for collaboration events.

Design principles:
- Every table carries ``workspace_id`` and/or ``organization_id`` so access is always scoped.
- ``Comment`` uses a generic ``target_type`` + ``target_id`` pair so any artifact type can be
  commented on without adding tables. This is the same pattern as ActivityEvent.
- ``Invitation`` uses a cryptographic token for email-based accept/decline (stateless link).
- Soft-delete via ``deleted_at`` (nullable) on Organization and Comment.
- ``VersionSnapshot`` stores the serialized state as JSON (the diff engine is a future concern).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _org_id() -> str:
    return f"org_{uuid.uuid4().hex[:16]}"


def _orgm_id() -> str:
    return f"orgm_{uuid.uuid4().hex[:14]}"


def _wsm_id() -> str:
    return f"wsm_{uuid.uuid4().hex[:16]}"


def _inv_id() -> str:
    return f"inv_{uuid.uuid4().hex[:16]}"


def _inv_token() -> str:
    return secrets.token_urlsafe(32)


def _comment_id() -> str:
    return f"cmt_{uuid.uuid4().hex[:16]}"


def _activity_id() -> str:
    return f"act_{uuid.uuid4().hex[:16]}"


def _version_id() -> str:
    return f"ver_{uuid.uuid4().hex[:16]}"


def _collab_log_id() -> str:
    return f"clog_{uuid.uuid4().hex[:14]}"


# ──────────────────────────────────────────────────────────── Organization


class Organization(Base):
    """A top-level entity that groups workspaces and users.

    Future enterprise tenants build on this model (Module 2 adds SSO, RBAC, governance
    on top; Module 4 adds multi-tenant deployment). The ``settings`` JSON column is
    intentionally schemaless so future features (SSO config, branding, quotas) slot in
    without migrations.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_org_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="🏢")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366f1")

    # The user who created the org (always has owner role in OrganizationMember too).
    creator_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # Plan / tier (free-form string; Module 2 governance gates on this).
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default="free")

    # Denormalized counters.
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    workspace_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Schemaless settings for future features (SSO config, branding, quotas, etc.).
    settings: Mapped[dict | None] = mapped_column(JSON, default=None)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        Index("ix_org_creator", "creator_id"),
    )


# ──────────────────────────────────────────────────────────── OrganizationMember


class OrganizationMember(Base):
    """User ↔ Organization membership with role.

    Roles (lightweight — Module 2 replaces with full RBAC):
    - ``owner``  — full control, can delete org, transfer ownership.
    - ``admin``  — can manage members and workspaces.
    - ``member`` — can access org workspaces they are invited to.
    """

    __tablename__ = "organization_members"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_orgm_id)
    organization_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")  # owner | admin | member

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        # One membership per (user, org).
        Index("ix_orgmem_org_user", "organization_id", "user_id", unique=True),
        Index("ix_orgmem_user", "user_id"),
    )


# ──────────────────────────────────────────────────────────── WorkspaceMember


class WorkspaceMember(Base):
    """User ↔ Workspace membership with role.

    Roles (lightweight — Module 2 replaces with full RBAC):
    - ``owner``  — the workspace creator. Full control.
    - ``editor`` — can read AND write all content.
    - ``viewer`` — read-only access.

    The workspace creator is auto-inserted as ``owner`` when the workspace is created.
    Other members are added via invitations or direct add (by owner/editor).
    """

    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_wsm_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")  # owner | editor | viewer

    # Which organization context this membership was created under (nullable for personal).
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)

    invited_by: Mapped[str | None] = mapped_column(String(40), default=None)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        # One membership per (user, workspace).
        Index("ix_wsmem_ws_user", "workspace_id", "user_id", unique=True),
        Index("ix_wsmem_user", "user_id"),
    )


# ──────────────────────────────────────────────────────────── Invitation


class Invitation(Base):
    """Email-based invitation to an organization or workspace.

    The token is a cryptographic random string (URL-safe) that the invitee receives via
    email or link. Accepting an invitation creates the corresponding membership row.

    ``target_type`` + ``target_id`` identify what the invite is for:
    - ``organization`` + org_id → OrganizationMember is created on accept.
    - ``workspace``    + ws_id  → WorkspaceMember is created on accept.
    """

    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_inv_id)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False, default=_inv_token)

    # What the invite is for.
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # organization | workspace
    target_id: Mapped[str] = mapped_column(String(40), nullable=False)    # org_id or ws_id
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")  # role to grant on accept

    # Who sent it and who it's for.
    inviter_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    invitee_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    invitee_user_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # set on accept

    # Lifecycle.
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="pending")
    # pending | accepted | declined | expired | revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_inv_target", "target_type", "target_id"),
    )


# ──────────────────────────────────────────────────────────── Comment


class Comment(Base):
    """Unified comment on any artifact in a workspace.

    ``target_type`` + ``target_id`` identify the artifact being commented on:
    - document, note, flashcard, summary, graph_entity, graph_relationship,
      ai_response, media, transcript, conversation, research_report, etc.

    Threading is via ``parent_comment_id`` (nullable). Top-level comments have None.
    Mentions are parsed from content and stored as a JSON list of user IDs.
    """

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_comment_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    author_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # What this comment is attached to.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)  # document | note | graph_entity | ...
    target_id: Mapped[str] = mapped_column(String(40), nullable=False)

    # Threading.
    parent_comment_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)

    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mentions: Mapped[list | None] = mapped_column(JSON, default=None)  # [user_id, ...]

    # Resolution (for review-style comments).
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_by: Mapped[str | None] = mapped_column(String(40), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    # Edit tracking.
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # denormalized

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        Index("ix_comment_target", "workspace_id", "target_type", "target_id"),
        Index("ix_comment_parent", "parent_comment_id"),
        Index("ix_comment_ws_created", "workspace_id", "created_at"),
    )


# ──────────────────────────────────────────────────────────── ActivityEvent


class ActivityEvent(Base):
    """Workspace activity feed entry.

    Every significant action in a workspace is recorded as an activity event so that the
    activity feed can show a chronological timeline of what happened. Events are immutable
    (write-once, never updated).

    ``event_type`` is a free-form string identifying the action. Examples:
    document_uploaded, note_created, graph_updated, agent_executed, comment_added,
    member_invited, member_joined, workspace_updated, flashcard_reviewed,
    summary_generated, media_processed, evaluation_run, etc.

    ``target_type`` + ``target_id`` identify the artifact the action was performed on.
    ``details`` is a schemaless JSON payload with event-specific data (e.g. filename,
    title, change summary).
    """

    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_activity_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)

    # What the action was performed on (nullable — some events are workspace-level).
    target_type: Mapped[str | None] = mapped_column(String(40), default=None)
    target_id: Mapped[str | None] = mapped_column(String(40), default=None)
    target_title: Mapped[str | None] = mapped_column(String(300), default=None)  # denormalized for display

    # Human-readable description of the event (e.g. "uploaded 'Chapter 3.pdf'").
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Schemaless event-specific data.
    details: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_activity_ws_created", "workspace_id", "created_at"),
        Index("ix_activity_ws_type", "workspace_id", "event_type"),
        Index("ix_activity_actor", "actor_id"),
    )


# ──────────────────────────────────────────────────────────── VersionSnapshot


class VersionSnapshot(Base):
    """Version history snapshot for editable artifacts.

    A snapshot is taken when a significant save occurs (e.g. note content change,
    graph entity edit, workspace metadata update). The full state is serialized
    into ``snapshot`` JSON so the artifact can be restored or diffed later.

    Future concerns (Module 2+): conflict resolution, branching, diff visualization,
    restoration. For now, this is an append-only history log.
    """

    __tablename__ = "version_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_version_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    # What artifact this version belongs to.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)  # note | document | graph_entity | ...
    target_id: Mapped[str] = mapped_column(String(40), nullable=False)

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # The full serialized state of the artifact at this version.
    snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)

    # A short human-readable description of what changed.
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Byte size of the snapshot (for quota/cleanup).
    snapshot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_version_target", "target_type", "target_id"),
        Index("ix_version_ws_created", "workspace_id", "created_at"),
    )


# ──────────────────────────────────────────────────────────── CollaborationLog


class CollaborationLog(Base):
    """Observability telemetry for collaboration events.

    This is the collaboration-specific telemetry table (consistent with RetrievalLog,
    AgentExecutionLog, SemanticMemoryLog, etc.). It never duplicates previous logs — it
    captures ONLY collaboration-specific events (workspace events, invitations, member
    changes, comments, shared AI usage, knowledge sharing, graph collaboration, presence,
    synchronization).
    """

    __tablename__ = "collaboration_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_collab_log_id)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)

    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    # Examples: org_created, member_invited, member_joined, member_removed,
    # workspace_shared, workspace_cloned, workspace_transferred, comment_added,
    # presence_update, sync_event, shared_ai_query, shared_graph_update, etc.

    target_type: Mapped[str | None] = mapped_column(String(40), default=None)
    target_id: Mapped[str | None] = mapped_column(String(40), default=None)

    # Outcome.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success | error
    error: Mapped[str | None] = mapped_column(Text, default=None)

    # Timing.
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Schemaless details (invitation token, member email, comment content hash, etc.).
    details: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_collablog_ws_created", "workspace_id", "created_at"),
        Index("ix_collablog_type", "event_type"),
    )
