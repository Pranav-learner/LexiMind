"""The keystone module: effective-owner resolution for shared workspaces.

Every existing LexiMind subsystem gates on ``(workspace_id, owner_id)``. Instead of
rewriting 30+ services, ``resolve_access`` translates a requesting user into the
**effective owner_id** that existing queries expect:

1. User **owns** the workspace → returns ``user_id`` (unchanged behavior).
2. User is a **member** of the workspace → returns the workspace's ``owner_id``.
3. Neither → raises ``AccessDenied``.

This means ChatService, KnowledgeService, DocumentService, AgentRuntime, etc. continue
to query ``WHERE owner_id = :effective AND workspace_id = :ws`` and automatically see the
shared data — zero service changes.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collaboration.errors import AccessDenied, InsufficientRole
from app.collaboration.models import WorkspaceMember
from app.collaboration.validation import ROLE_HIERARCHY
from app.workspaces.models import Workspace


def resolve_access(
    user_id: str,
    workspace_id: str,
    db: Session,
    *,
    min_role: str = "viewer",
) -> str:
    """Return the effective ``owner_id`` for data queries, or raise ``AccessDenied``.

    Parameters
    ----------
    user_id : str
        The requesting user.
    workspace_id : str
        The workspace being accessed.
    db : Session
        Active database session.
    min_role : str
        Minimum role required (viewer | editor | owner). Default "viewer".

    Returns
    -------
    str
        The **effective owner_id** to use in downstream queries. This is always the
        workspace's ``owner_id``, regardless of who the requesting user is.
    """
    # Step 1: Load the workspace.
    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if ws is None:
        raise AccessDenied("Workspace not found or you do not have access.")

    # Step 2: Check if the user is the workspace owner (fast path).
    if ws.owner_id == user_id:
        return ws.owner_id

    # Step 3: Check workspace membership.
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if membership is None:
        raise AccessDenied("You do not have access to this workspace.")

    # Step 4: Check minimum role.
    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    required_level = ROLE_HIERARCHY.get(min_role, 0)
    if user_level < required_level:
        raise InsufficientRole(required=min_role, actual=membership.role)

    # Return the workspace owner's ID — this is the key trick that makes all existing
    # owner-scoped queries work for shared workspaces.
    return ws.owner_id


def get_membership(
    user_id: str,
    workspace_id: str,
    db: Session,
) -> Optional[WorkspaceMember]:
    """Return the user's workspace membership, or None if not a member."""
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )


def is_member(user_id: str, workspace_id: str, db: Session) -> bool:
    """Check if a user is a member of a workspace (including owner)."""
    # Check ownership first.
    ws = db.scalar(
        select(Workspace.owner_id).where(
            Workspace.id == workspace_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if ws is not None and ws == user_id:
        return True
    # Check membership table.
    return get_membership(user_id, workspace_id, db) is not None


def require_role(
    user_id: str,
    workspace_id: str,
    min_role: str,
    db: Session,
) -> str:
    """Like ``resolve_access`` but with an explicit minimum role requirement.

    This is a convenience alias — ``resolve_access`` already accepts ``min_role``.
    """
    return resolve_access(user_id, workspace_id, db, min_role=min_role)


def get_user_role(user_id: str, workspace_id: str, db: Session) -> Optional[str]:
    """Return the user's role in a workspace, or None if not a member.

    The workspace owner always has 'owner' role even if no explicit membership row exists.
    """
    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if ws is None:
        return None
    if ws.owner_id == user_id:
        return "owner"
    m = get_membership(user_id, workspace_id, db)
    return m.role if m else None
