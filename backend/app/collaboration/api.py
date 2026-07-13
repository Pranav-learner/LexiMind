"""Phase 9 · Module 1 — Collaboration API router.

All collaboration endpoints live here. Consistent with the project's existing pattern
of one ``router`` object per module, mounted in ``main.py``.

Endpoint groups:
1. Organizations — CRUD + member management
2. Workspace members — add, remove, change role, list
3. Invitations — create, accept, decline, list
4. Comments — unified commenting on any artifact
5. Activity feed — workspace timeline
6. Version history — artifact version snapshots
7. Presence — real-time online status
8. Sync — long-poll for workspace changes
9. Workspace operations — clone, transfer ownership
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.collaboration.access import resolve_access, get_user_role
from app.collaboration.activity_service import ActivityService
from app.collaboration.comment_service import CommentService
from app.collaboration.errors import CollaborationError
from app.collaboration.organization_service import OrganizationService
from app.collaboration.presence import presence_store
from app.collaboration.schemas import (
    ActivityEventOut,
    CommentCreate,
    CommentOut,
    CommentUpdate,
    InvitationCreate,
    InvitationOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    OrgMemberAdd,
    OrgMemberOut,
    PresenceHeartbeat,
    PresenceOut,
    PresenceEntry,
    SyncPollOut,
    VersionSnapshotOut,
    WorkspaceCloneRequest,
    WorkspaceMemberAdd,
    WorkspaceMemberOut,
    WorkspaceMemberUpdate,
    WorkspaceTransferRequest,
)
from app.collaboration.sync import sync_bus
from app.collaboration.version_service import VersionService
from app.collaboration.workspace_collaboration_service import WorkspaceCollaborationService
from app.db.base import get_db

router = APIRouter(prefix="/collaboration", tags=["collaboration"])

# Service singletons (stateless — safe to share across requests).
_org_svc = OrganizationService()
_ws_collab_svc = WorkspaceCollaborationService()
_comment_svc = CommentService()
_activity_svc = ActivityService()
_version_svc = VersionService()


def _handle_error(e: CollaborationError):
    raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": str(e)})


# ════════════════════════════════════════════════════════════════════════
#  1. Organizations
# ════════════════════════════════════════════════════════════════════════


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(
    body: OrganizationCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        org = _org_svc.create(
            db,
            creator_id=user_id,
            name=body.name,
            description=body.description,
            icon=body.icon,
            color=body.color,
            slug=body.slug,
        )
        return OrganizationOut.model_validate(org)
    except CollaborationError as e:
        _handle_error(e)


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    orgs = _org_svc.list_for_user(db, user_id)
    return [OrganizationOut.model_validate(o) for o in orgs]


@router.get("/organizations/{org_id}", response_model=OrganizationOut)
def get_organization(
    org_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        org = _org_svc.get(db, org_id)
        return OrganizationOut.model_validate(org)
    except CollaborationError as e:
        _handle_error(e)


@router.patch("/organizations/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: str,
    body: OrganizationUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        org = _org_svc.update(
            db, org_id,
            name=body.name,
            description=body.description,
            icon=body.icon,
            color=body.color,
        )
        return OrganizationOut.model_validate(org)
    except CollaborationError as e:
        _handle_error(e)


@router.delete("/organizations/{org_id}", status_code=204)
def delete_organization(
    org_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        _org_svc.delete(db, org_id, actor_id=user_id)
    except CollaborationError as e:
        _handle_error(e)


# ────────── Organization Members


@router.post("/organizations/{org_id}/members", response_model=OrgMemberOut, status_code=201)
def add_org_member(
    org_id: str,
    body: OrgMemberAdd,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        member = _org_svc.add_member(db, org_id, user_id=body.user_id, role=body.role)
        return OrgMemberOut.model_validate(member)
    except CollaborationError as e:
        _handle_error(e)


@router.get("/organizations/{org_id}/members", response_model=list[OrgMemberOut])
def list_org_members(
    org_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        members = _org_svc.list_members(db, org_id)
        return [OrgMemberOut.model_validate(m) for m in members]
    except CollaborationError as e:
        _handle_error(e)


@router.delete("/organizations/{org_id}/members/{member_user_id}", status_code=204)
def remove_org_member(
    org_id: str,
    member_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        _org_svc.remove_member(db, org_id, member_user_id)
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  2. Workspace Members
# ════════════════════════════════════════════════════════════════════════


@router.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberOut, status_code=201)
def add_workspace_member(
    workspace_id: str,
    body: WorkspaceMemberAdd,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        # If user_id is provided, add directly. If email, create invitation.
        if body.user_id:
            member = _ws_collab_svc.add_member(
                db, workspace_id,
                user_id=body.user_id,
                role=body.role,
                invited_by=user_id,
            )
            # Record activity.
            _activity_svc.record(
                db, workspace_id=workspace_id, actor_id=user_id,
                event_type="member_added",
                description=f"Added member {body.user_id} as {body.role}",
                target_type="user", target_id=body.user_id,
            )
            return WorkspaceMemberOut.model_validate(member)
        elif body.email:
            inv = _ws_collab_svc.invite(
                db, target_type="workspace", target_id=workspace_id,
                inviter_id=user_id, email=body.email, role=body.role,
            )
            # Return a synthetic member out (pending).
            return WorkspaceMemberOut(
                id=inv.id, workspace_id=workspace_id,
                user_id="", role=body.role,
                invited_by=user_id, joined_at=inv.created_at,
                email=body.email,
            )
        else:
            raise HTTPException(400, detail="Either user_id or email is required.")
    except CollaborationError as e:
        _handle_error(e)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_workspace_members(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        members = _ws_collab_svc.list_members(db, workspace_id)
        return [WorkspaceMemberOut.model_validate(m) for m in members]
    except CollaborationError as e:
        _handle_error(e)


@router.patch("/workspaces/{workspace_id}/members/{member_user_id}", response_model=WorkspaceMemberOut)
def change_member_role(
    workspace_id: str,
    member_user_id: str,
    body: WorkspaceMemberUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        member = _ws_collab_svc.change_role(
            db, workspace_id, member_user_id, body.role, actor_id=user_id,
        )
        return WorkspaceMemberOut.model_validate(member)
    except CollaborationError as e:
        _handle_error(e)


@router.delete("/workspaces/{workspace_id}/members/{member_user_id}", status_code=204)
def remove_workspace_member(
    workspace_id: str,
    member_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        _ws_collab_svc.remove_member(db, workspace_id, member_user_id, actor_id=user_id)
        _activity_svc.record(
            db, workspace_id=workspace_id, actor_id=user_id,
            event_type="member_removed",
            description=f"Removed member {member_user_id}",
            target_type="user", target_id=member_user_id,
        )
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  3. Invitations
# ════════════════════════════════════════════════════════════════════════


@router.post("/workspaces/{workspace_id}/invitations", response_model=InvitationOut, status_code=201)
def create_invitation(
    workspace_id: str,
    body: InvitationCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        inv = _ws_collab_svc.invite(
            db, target_type="workspace", target_id=workspace_id,
            inviter_id=user_id, email=body.email, role=body.role,
        )
        _activity_svc.record(
            db, workspace_id=workspace_id, actor_id=user_id,
            event_type="invitation_sent",
            description=f"Invited {body.email} as {body.role}",
            details={"email": body.email, "role": body.role},
        )
        return InvitationOut.model_validate(inv)
    except CollaborationError as e:
        _handle_error(e)


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationOut])
def list_invitations(
    workspace_id: str,
    status: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        invitations = _ws_collab_svc.list_invitations(db, "workspace", workspace_id, status=status)
        return [InvitationOut.model_validate(i) for i in invitations]
    except CollaborationError as e:
        _handle_error(e)


@router.post("/invitations/{token}/accept", response_model=InvitationOut)
def accept_invitation(
    token: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        inv = _ws_collab_svc.accept_invitation(db, token, user_id=user_id)
        if inv.target_type == "workspace":
            _activity_svc.record(
                db, workspace_id=inv.target_id, actor_id=user_id,
                event_type="member_joined",
                description="Joined via invitation",
            )
        return InvitationOut.model_validate(inv)
    except CollaborationError as e:
        _handle_error(e)


@router.post("/invitations/{token}/decline", response_model=InvitationOut)
def decline_invitation(
    token: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        inv = _ws_collab_svc.decline_invitation(db, token)
        return InvitationOut.model_validate(inv)
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  4. Comments
# ════════════════════════════════════════════════════════════════════════


@router.post("/workspaces/{workspace_id}/comments", response_model=CommentOut, status_code=201)
def create_comment(
    workspace_id: str,
    body: CommentCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        comment = _comment_svc.create(
            db, workspace_id=workspace_id, author_id=user_id,
            target_type=body.target_type, target_id=body.target_id,
            content=body.content, parent_comment_id=body.parent_comment_id,
            mentions=body.mentions,
        )
        _activity_svc.record(
            db, workspace_id=workspace_id, actor_id=user_id,
            event_type="comment_added",
            description=f"Commented on {body.target_type}",
            target_type=body.target_type, target_id=body.target_id,
        )
        sync_bus.publish(
            workspace_id, "comment",
            actor_id=user_id,
            target_type=body.target_type, target_id=body.target_id,
            data={"comment_id": comment.id, "action": "created"},
        )
        return CommentOut.model_validate(comment)
    except CollaborationError as e:
        _handle_error(e)


@router.get("/workspaces/{workspace_id}/comments", response_model=list[CommentOut])
def list_comments(
    workspace_id: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        if target_type and target_id:
            comments = _comment_svc.list_for_target(
                db, workspace_id, target_type, target_id, limit=limit, offset=offset,
            )
        else:
            comments = _comment_svc.list_for_workspace(
                db, workspace_id, limit=limit, offset=offset,
            )
        return [CommentOut.model_validate(c) for c in comments]
    except CollaborationError as e:
        _handle_error(e)


@router.patch("/collaboration/comments/{comment_id}", response_model=CommentOut)
def edit_comment(
    comment_id: str,
    body: CommentUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        comment = _comment_svc.edit(db, comment_id, actor_id=user_id, content=body.content)
        return CommentOut.model_validate(comment)
    except CollaborationError as e:
        _handle_error(e)


@router.delete("/collaboration/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        _comment_svc.delete(db, comment_id, actor_id=user_id)
    except CollaborationError as e:
        _handle_error(e)


@router.post("/collaboration/comments/{comment_id}/resolve", response_model=CommentOut)
def resolve_comment(
    comment_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        comment = _comment_svc.resolve(db, comment_id, resolver_id=user_id)
        return CommentOut.model_validate(comment)
    except CollaborationError as e:
        _handle_error(e)


@router.post("/collaboration/comments/{comment_id}/unresolve", response_model=CommentOut)
def unresolve_comment(
    comment_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        comment = _comment_svc.unresolve(db, comment_id)
        return CommentOut.model_validate(comment)
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  5. Activity Feed
# ════════════════════════════════════════════════════════════════════════


@router.get("/workspaces/{workspace_id}/activity", response_model=list[ActivityEventOut])
def list_activity(
    workspace_id: str,
    event_type: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        events = _activity_svc.list_for_workspace(
            db, workspace_id, limit=limit, offset=offset, event_type=event_type,
        )
        return [ActivityEventOut.model_validate(e) for e in events]
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  6. Version History
# ════════════════════════════════════════════════════════════════════════


@router.get("/workspaces/{workspace_id}/versions", response_model=list[VersionSnapshotOut])
def list_versions(
    workspace_id: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        if target_type and target_id:
            versions = _version_svc.list_for_target(
                db, target_type, target_id, limit=limit, offset=offset,
            )
        else:
            versions = _version_svc.list_for_workspace(
                db, workspace_id, limit=limit, offset=offset,
            )
        return [VersionSnapshotOut.model_validate(v) for v in versions]
    except CollaborationError as e:
        _handle_error(e)


@router.get("/collaboration/versions/{version_id}", response_model=VersionSnapshotOut)
def get_version(
    version_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        vs = _version_svc.get(db, version_id)
        return VersionSnapshotOut.model_validate(vs)
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  7. Presence
# ════════════════════════════════════════════════════════════════════════


@router.get("/workspaces/{workspace_id}/presence", response_model=PresenceOut)
def get_presence(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        online = presence_store.get_online(workspace_id)
        entries = []
        for p in online:
            entries.append(PresenceEntry(
                user_id=p["user_id"],
                display_name=p.get("display_name"),
                status=p.get("status", "online"),
                active_document_id=p.get("active_document_id"),
                active_artifact_type=p.get("active_artifact_type"),
                active_artifact_id=p.get("active_artifact_id"),
                last_seen=p["last_seen"],
            ))
        return PresenceOut(members=entries, total_online=len(entries))
    except CollaborationError as e:
        _handle_error(e)


@router.post("/workspaces/{workspace_id}/presence/heartbeat", status_code=204)
def heartbeat(
    workspace_id: str,
    body: PresenceHeartbeat,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        presence_store.heartbeat(
            workspace_id, user_id,
            status=body.status,
            active_document_id=body.active_document_id,
            active_artifact_type=body.active_artifact_type,
            active_artifact_id=body.active_artifact_id,
        )
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  8. Sync (Long-Poll)
# ════════════════════════════════════════════════════════════════════════


@router.get("/workspaces/{workspace_id}/sync")
def poll_sync(
    workspace_id: str,
    cursor: Optional[str] = None,
    timeout: int = Query(default=30, le=30, ge=1),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        events, new_cursor = sync_bus.poll(workspace_id, cursor, timeout=timeout)
        return SyncPollOut(
            events=[
                {
                    "event_type": e.event_type,
                    "workspace_id": e.workspace_id,
                    "actor_id": e.actor_id,
                    "target_type": e.target_type,
                    "target_id": e.target_id,
                    "data": e.data,
                    "timestamp": e.timestamp,
                }
                for e in events
            ],
            cursor=new_cursor,
        )
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  9. Workspace Operations
# ════════════════════════════════════════════════════════════════════════


@router.post("/workspaces/{workspace_id}/clone", status_code=201)
def clone_workspace(
    workspace_id: str,
    body: WorkspaceCloneRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        resolve_access(user_id, workspace_id, db)
        new_ws = _ws_collab_svc.clone_workspace(
            db, workspace_id,
            new_owner_id=user_id,
            name=body.name,
            description=body.description,
        )
        _activity_svc.record(
            db, workspace_id=workspace_id, actor_id=user_id,
            event_type="workspace_cloned",
            description=f"Cloned workspace as '{body.name}'",
            details={"new_workspace_id": new_ws.id},
        )
        return {"id": new_ws.id, "name": new_ws.name}
    except CollaborationError as e:
        _handle_error(e)


@router.post("/workspaces/{workspace_id}/transfer")
def transfer_workspace(
    workspace_id: str,
    body: WorkspaceTransferRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        ws = _ws_collab_svc.transfer_ownership(
            db, workspace_id,
            current_owner_id=user_id,
            new_owner_id=body.new_owner_id,
        )
        _activity_svc.record(
            db, workspace_id=workspace_id, actor_id=user_id,
            event_type="ownership_transferred",
            description=f"Transferred ownership to {body.new_owner_id}",
            target_type="user", target_id=body.new_owner_id,
        )
        return {"id": ws.id, "owner_id": ws.owner_id}
    except CollaborationError as e:
        _handle_error(e)


# ════════════════════════════════════════════════════════════════════════
#  10. Access check utility endpoint
# ════════════════════════════════════════════════════════════════════════


@router.get("/workspaces/{workspace_id}/access")
def check_access(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Check the current user's access level in a workspace."""
    role = get_user_role(user_id, workspace_id, db)
    return {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "role": role,
        "has_access": role is not None,
    }
