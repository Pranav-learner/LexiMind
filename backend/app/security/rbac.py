"""Role-Based Access Control (RBAC) Engine.

Evaluates permissions based on system roles (owner, admin, editor, viewer),
custom roles, team inheritance, and workspace ownership.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.collaboration.models import OrganizationMember, WorkspaceMember
from app.security.models import CustomRole, RoleAssignment, TeamMember
from app.workspaces.models import Workspace

# Hierarchical permission mappings for system roles
SYSTEM_ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {
        "workspace.read",
        "workspace.write",
        "workspace.admin",
        "document.read",
        "document.write",
        "document.delete",
        "chat.read",
        "chat.write",
        "chat.delete",
        "note.read",
        "note.write",
        "note.delete",
        "graph.read",
        "graph.write",
        "agent.read",
        "agent.write",
        "agent.execute",
        "observability.read",
        "eval.read",
        "compliance.admin",
        "security.admin",
    },
    "editor": {
        "workspace.read",
        "document.read",
        "document.write",
        "chat.read",
        "chat.write",
        "note.read",
        "note.write",
        "graph.read",
        "graph.write",
        "agent.read",
        "agent.execute",
        "observability.read",
    },
    "viewer": {
        "workspace.read",
        "document.read",
        "chat.read",
        "note.read",
        "graph.read",
        "agent.read",
    },
}


def match_permission(required: str, granted_perms: set[str]) -> bool:
    """Check if required permission matches any of the granted permissions (supports wildcards)."""
    if "*" in granted_perms:
        return True
    if required in granted_perms:
        return True

    # Support segment wildcards like 'document.*'
    if "." in required:
        category = required.split(".")[0]
        if f"{category}.*" in granted_perms:
            return True

    return False


def get_effective_permissions(
    db: Session,
    actor_id: str,
    workspace_id: str | None = None,
    organization_id: str | None = None,
) -> set[str]:
    """Resolve and collect all permissions granted to an actor (user or service account)."""
    permissions: set[str] = set()

    # 1. Workspace Direct Ownership Check
    if workspace_id:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.deleted_at.is_(None)).first()
        if ws and ws.owner_id == actor_id:
            return {"*"}  # Creator has wildcard permissions
        
        # Override Org ID if workspace defines it
        if ws and ws.organization_id:
            organization_id = ws.organization_id

    # 2. Collect roles assigned directly to user or service account
    assignments = db.query(RoleAssignment).filter(
        (RoleAssignment.user_id == actor_id) | (RoleAssignment.service_account_id == actor_id)
    ).all()

    for assignment in assignments:
        # Filter assignments by scope
        if assignment.workspace_id and assignment.workspace_id != workspace_id:
            continue
        if assignment.organization_id and assignment.organization_id != organization_id:
            continue

        _add_role_permissions(db, assignment.role_type, assignment.role_name, permissions)

    # 3. Inherit via Team Memberships
    teams = db.query(TeamMember).filter(TeamMember.user_id == actor_id).all()
    if teams:
        team_ids = [t.team_id for t in teams]
        team_assignments = db.query(RoleAssignment).filter(RoleAssignment.team_id.in_(team_ids)).all()
        for assignment in team_assignments:
            if assignment.workspace_id and assignment.workspace_id != workspace_id:
                continue
            if assignment.organization_id and assignment.organization_id != organization_id:
                continue
            _add_role_permissions(db, assignment.role_type, assignment.role_name, permissions)

    # 4. Fallback to Collaboration Workspace Roles (from WorkspaceMember)
    if workspace_id:
        wsm = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == actor_id,
        ).first()
        if wsm:
            _add_role_permissions(db, "system", wsm.role, permissions)

    # 5. Fallback to Collaboration Org Roles (from OrganizationMember)
    if organization_id:
        orgm = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == actor_id,
        ).first()
        if orgm:
            _add_role_permissions(db, "system", orgm.role, permissions)

    # 6. Baseline permissions for global/unscoped actions of authenticated actors
    if not workspace_id and not organization_id:
        permissions.update({
            "workspace.read",
            "workspace.write",
            "org.read",
            "org.write",
            "document.read",
            "document.write",
            "chat.read",
            "chat.write",
            "note.read",
            "note.write",
            "agent.read",
            "agent.execute",
        })

    return permissions


def _add_role_permissions(db: Session, role_type: str, role_name: str, out_perms: set[str]) -> None:
    """Helper to append permissions matching a role definition."""
    if role_type == "system":
        # Hierarchical inclusion
        if role_name in SYSTEM_ROLE_PERMISSIONS:
            out_perms.update(SYSTEM_ROLE_PERMISSIONS[role_name])
    elif role_type == "custom":
        custom = db.query(CustomRole).filter(CustomRole.id == role_name).first()
        if custom:
            out_perms.update(custom.permissions)


def has_permission(
    db: Session,
    actor_id: str,
    action: str,
    workspace_id: str | None = None,
    organization_id: str | None = None,
) -> bool:
    """Verify if the actor has permission to perform an action on a workspace or organization."""
    # Special bypass: if actor_id is the system/root user (e.g., when doing background indexing or evaluation tasks)
    if actor_id == "system":
        return True

    granted = get_effective_permissions(db, actor_id, workspace_id, organization_id)
    return match_permission(action, granted)
