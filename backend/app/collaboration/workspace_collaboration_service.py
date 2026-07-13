"""Shared workspace lifecycle business logic.

Handles invitations, member management, workspace cloning, ownership transfer.
Transport-agnostic — never imports FastAPI.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.collaboration.errors import (
    AccessDenied,
    AlreadyMember,
    CannotChangeOwnRole,
    CannotRemoveOwner,
    CollaborationValidationError,
    InsufficientRole,
    InvitationAlreadyProcessed,
    InvitationExpired,
    InvitationNotFound,
    NotAMember,
)
from app.collaboration.models import Invitation, WorkspaceMember
from app.collaboration.validation import role_gte, validate_email, validate_ws_role
from app.collaboration.workspace_collaboration_repository import WorkspaceCollaborationRepository
from app.workspaces.models import Workspace


INVITATION_TTL_DAYS = 7


class WorkspaceCollaborationService:

    def __init__(self, repo: WorkspaceCollaborationRepository | None = None):
        self.repo = repo or WorkspaceCollaborationRepository()

    # ────────────────────────────────── Members

    def add_member(
        self,
        db: Session,
        workspace_id: str,
        *,
        user_id: str,
        role: str = "editor",
        invited_by: str | None = None,
        organization_id: str | None = None,
    ) -> WorkspaceMember:
        role = validate_ws_role(role)

        # Prevent duplicate membership.
        existing = self.repo.get_member(db, workspace_id, user_id)
        if existing:
            raise AlreadyMember("workspace")

        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            organization_id=organization_id,
        )
        self.repo.add_member(db, member)

        # Update workspace member count.
        db.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(member_count=Workspace.member_count + 1, is_shared=True)
        )
        db.commit()
        return member

    def remove_member(
        self,
        db: Session,
        workspace_id: str,
        user_id: str,
        *,
        actor_id: str,
    ) -> None:
        # Fetch workspace to check ownership.
        ws = db.scalar(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        if ws is None:
            raise CollaborationValidationError("Workspace not found.")

        # Cannot remove the workspace owner.
        if ws.owner_id == user_id:
            raise CannotRemoveOwner()

        member = self.repo.get_member(db, workspace_id, user_id)
        if member is None:
            raise NotAMember("workspace")

        # Only owner or the member themselves can remove.
        if actor_id != user_id and ws.owner_id != actor_id:
            actor_member = self.repo.get_member(db, workspace_id, actor_id)
            if actor_member is None or not role_gte(actor_member.role, "editor"):
                raise AccessDenied("Only workspace editors or owners can remove members.")

        self.repo.remove_member(db, member)

        # Update workspace member count.
        new_count = self.repo.count_members(db, workspace_id)
        db.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(
                member_count=new_count + 1,  # +1 for the owner (not in members table)
                is_shared=new_count > 0,
            )
        )
        db.commit()

    def change_role(
        self,
        db: Session,
        workspace_id: str,
        user_id: str,
        new_role: str,
        *,
        actor_id: str,
    ) -> WorkspaceMember:
        new_role = validate_ws_role(new_role)

        if user_id == actor_id:
            raise CannotChangeOwnRole()

        member = self.repo.get_member(db, workspace_id, user_id)
        if member is None:
            raise NotAMember("workspace")

        self.repo.update_member_role(db, member, new_role)
        db.commit()
        return member

    def list_members(self, db: Session, workspace_id: str) -> list[WorkspaceMember]:
        return self.repo.list_members(db, workspace_id)

    def get_member(self, db: Session, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        return self.repo.get_member(db, workspace_id, user_id)

    # ────────────────────────────────── Invitations

    def invite(
        self,
        db: Session,
        *,
        target_type: str,
        target_id: str,
        inviter_id: str,
        email: str,
        role: str = "editor",
    ) -> Invitation:
        email = validate_email(email)
        role = validate_ws_role(role) if target_type == "workspace" else role

        inv = Invitation(
            target_type=target_type,
            target_id=target_id,
            inviter_id=inviter_id,
            invitee_email=email,
            role=role,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=INVITATION_TTL_DAYS),
        )
        self.repo.create_invitation(db, inv)
        db.commit()
        return inv

    def accept_invitation(
        self,
        db: Session,
        token: str,
        *,
        user_id: str,
    ) -> Invitation:
        inv = self.repo.get_invitation_by_token(db, token)
        if inv is None:
            raise InvitationNotFound(token)

        if inv.status != "pending":
            raise InvitationAlreadyProcessed(inv.status)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if inv.expires_at and inv.expires_at < now:
            self.repo.update_invitation_status(db, inv, "expired")
            db.commit()
            raise InvitationExpired()

        # Create the membership.
        if inv.target_type == "workspace":
            existing = self.repo.get_member(db, inv.target_id, user_id)
            if not existing:
                member = WorkspaceMember(
                    workspace_id=inv.target_id,
                    user_id=user_id,
                    role=inv.role,
                    invited_by=inv.inviter_id,
                )
                self.repo.add_member(db, member)
                db.execute(
                    update(Workspace)
                    .where(Workspace.id == inv.target_id)
                    .values(member_count=Workspace.member_count + 1, is_shared=True)
                )
        elif inv.target_type == "organization":
            from app.collaboration.models import OrganizationMember
            from app.collaboration.organization_repository import OrganizationRepository

            org_repo = OrganizationRepository()
            existing = org_repo.get_member(db, inv.target_id, user_id)
            if not existing:
                om = OrganizationMember(
                    organization_id=inv.target_id,
                    user_id=user_id,
                    role=inv.role,
                )
                org_repo.add_member(db, om)
                org_repo.increment_member_count(db, inv.target_id)

        self.repo.update_invitation_status(db, inv, "accepted", user_id=user_id)
        db.commit()
        return inv

    def decline_invitation(self, db: Session, token: str) -> Invitation:
        inv = self.repo.get_invitation_by_token(db, token)
        if inv is None:
            raise InvitationNotFound(token)
        if inv.status != "pending":
            raise InvitationAlreadyProcessed(inv.status)
        self.repo.update_invitation_status(db, inv, "declined")
        db.commit()
        return inv

    def list_invitations(
        self,
        db: Session,
        target_type: str,
        target_id: str,
        *,
        status: str | None = None,
    ) -> list[Invitation]:
        return self.repo.list_invitations(db, target_type, target_id, status=status)

    # ────────────────────────────────── Workspace clone

    def clone_workspace(
        self,
        db: Session,
        workspace_id: str,
        *,
        new_owner_id: str,
        name: str,
        description: str = "",
    ) -> Workspace:
        """Create a new workspace as a copy of an existing one (metadata only).

        Content (documents, notes, etc.) is NOT cloned — they stay in the original
        workspace. Only the workspace metadata is duplicated. This is a lightweight
        "fork" operation.
        """
        from app.workspaces.validation import validate_name, validate_description as ws_validate_desc

        source = db.scalar(select(Workspace).where(Workspace.id == workspace_id))
        if source is None:
            raise CollaborationValidationError("Source workspace not found.")

        import uuid
        new_ws = Workspace(
            id=f"ws_{uuid.uuid4().hex[:16]}",
            owner_id=new_owner_id,
            name=validate_name(name),
            description=ws_validate_desc(description) if description else source.description,
            icon=source.icon,
            color=source.color,
        )
        db.add(new_ws)
        db.commit()
        return new_ws

    # ────────────────────────────────── Transfer ownership

    def transfer_ownership(
        self,
        db: Session,
        workspace_id: str,
        *,
        current_owner_id: str,
        new_owner_id: str,
    ) -> Workspace:
        ws = db.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.owner_id == current_owner_id,
            )
        )
        if ws is None:
            raise CollaborationValidationError(
                "Workspace not found or you are not the owner."
            )

        # Transfer ownership.
        ws.owner_id = new_owner_id

        # Ensure new owner has a membership row.
        new_member = self.repo.get_member(db, workspace_id, new_owner_id)
        if new_member:
            self.repo.update_member_role(db, new_member, "owner")
        else:
            self.repo.add_member(db, WorkspaceMember(
                workspace_id=workspace_id,
                user_id=new_owner_id,
                role="owner",
            ))

        # Downgrade old owner to editor in membership.
        old_member = self.repo.get_member(db, workspace_id, current_owner_id)
        if old_member:
            self.repo.update_member_role(db, old_member, "editor")
        else:
            self.repo.add_member(db, WorkspaceMember(
                workspace_id=workspace_id,
                user_id=current_owner_id,
                role="editor",
            ))

        db.commit()
        return ws
