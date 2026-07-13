"""Pydantic DTOs for all collaboration API endpoints.

Consistent with the existing project pattern: plain Pydantic models (v2 style),
no SQLAlchemy leakage. Every ``Out`` model uses ``model_config = ConfigDict(from_attributes=True)``
for ORM → DTO conversion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────── Organization


class OrganizationCreate(BaseModel):
    name: str
    description: str = ""
    icon: str = "🏢"
    color: str = "#6366f1"
    slug: str | None = None  # auto-generated from name if not provided


class OrganizationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str
    icon: str
    color: str
    creator_id: str
    plan: str
    member_count: int
    workspace_count: int
    created_at: datetime
    updated_at: datetime


# ──────────────────────────────────────────────────── OrganizationMember


class OrgMemberAdd(BaseModel):
    user_id: str
    role: str = "member"  # owner | admin | member


class OrgMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    user_id: str
    role: str
    joined_at: datetime

    # Denormalized user info (populated by the service, not the ORM).
    display_name: str | None = None
    email: str | None = None


# ──────────────────────────────────────────────────── WorkspaceMember


class WorkspaceMemberAdd(BaseModel):
    """Add a user directly (by user_id) or invite by email."""
    user_id: str | None = None
    email: str | None = None
    role: str = "editor"  # owner | editor | viewer


class WorkspaceMemberUpdate(BaseModel):
    role: str  # editor | viewer


class WorkspaceMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    user_id: str
    role: str
    organization_id: str | None = None
    invited_by: str | None = None
    joined_at: datetime

    # Denormalized user info (populated by the service).
    display_name: str | None = None
    email: str | None = None


# ──────────────────────────────────────────────────── Invitation


class InvitationCreate(BaseModel):
    email: str
    role: str = "editor"  # role to grant on accept
    target_type: str = "workspace"  # organization | workspace
    target_id: str = ""


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    token: str
    target_type: str
    target_id: str
    role: str
    inviter_id: str
    invitee_email: str
    invitee_user_id: str | None = None
    status: str
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime


# ──────────────────────────────────────────────────── Comment


class CommentCreate(BaseModel):
    target_type: str  # document | note | graph_entity | ...
    target_id: str
    content: str
    parent_comment_id: str | None = None
    mentions: list[str] | None = None


class CommentUpdate(BaseModel):
    content: str


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    author_id: str
    target_type: str
    target_id: str
    parent_comment_id: str | None = None
    content: str
    mentions: list[str] | None = None
    is_resolved: bool
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    is_edited: bool
    edit_count: int
    reply_count: int
    created_at: datetime
    updated_at: datetime

    # Denormalized author info (populated by the service).
    author_name: str | None = None


# ──────────────────────────────────────────────────── ActivityEvent


class ActivityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    actor_id: str
    event_type: str
    target_type: str | None = None
    target_id: str | None = None
    target_title: str | None = None
    description: str
    details: dict | None = None
    created_at: datetime

    # Denormalized actor info (populated by the service).
    actor_name: str | None = None


# ──────────────────────────────────────────────────── VersionSnapshot


class VersionSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    actor_id: str
    target_type: str
    target_id: str
    version_number: int
    change_summary: str
    snapshot_size: int
    created_at: datetime

    # Snapshot content is omitted in listings; fetched on demand.
    snapshot: dict | None = None


# ──────────────────────────────────────────────────── Presence


class PresenceHeartbeat(BaseModel):
    """Sent by a client to report presence and current activity."""
    active_document_id: str | None = None
    active_artifact_type: str | None = None  # document | note | graph | chat | ...
    active_artifact_id: str | None = None
    status: str = "online"  # online | away | busy


class PresenceEntry(BaseModel):
    user_id: str
    display_name: str | None = None
    status: str = "online"
    active_document_id: str | None = None
    active_artifact_type: str | None = None
    active_artifact_id: str | None = None
    last_seen: datetime


class PresenceOut(BaseModel):
    members: list[PresenceEntry]
    total_online: int


# ──────────────────────────────────────────────────── Sync


class SyncEvent(BaseModel):
    """A real-time change event pushed to clients via long-poll."""
    event_type: str  # document_update | knowledge_update | comment | presence | ...
    workspace_id: str
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    data: dict[str, Any] | None = None
    timestamp: datetime


class SyncPollOut(BaseModel):
    events: list[SyncEvent]
    cursor: str  # opaque cursor for the next poll


# ──────────────────────────────────────────────────── Workspace clone / transfer


class WorkspaceCloneRequest(BaseModel):
    name: str
    description: str = ""


class WorkspaceTransferRequest(BaseModel):
    new_owner_id: str
