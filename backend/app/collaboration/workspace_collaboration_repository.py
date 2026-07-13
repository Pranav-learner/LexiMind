"""Data-access layer for WorkspaceMember and Invitation tables.

Pure SQL queries — no business logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.collaboration.models import Invitation, WorkspaceMember


class WorkspaceCollaborationRepository:

    # ────────────────────────────────── WorkspaceMember

    @staticmethod
    def add_member(db: Session, member: WorkspaceMember) -> WorkspaceMember:
        db.add(member)
        db.flush()
        return member

    @staticmethod
    def get_member(db: Session, workspace_id: str, user_id: str) -> Optional[WorkspaceMember]:
        return db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )

    @staticmethod
    def list_members(db: Session, workspace_id: str) -> list[WorkspaceMember]:
        return list(
            db.scalars(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
                .order_by(WorkspaceMember.joined_at)
            )
        )

    @staticmethod
    def remove_member(db: Session, member: WorkspaceMember) -> None:
        db.delete(member)
        db.flush()

    @staticmethod
    def update_member_role(db: Session, member: WorkspaceMember, role: str) -> WorkspaceMember:
        member.role = role
        db.flush()
        return member

    @staticmethod
    def count_members(db: Session, workspace_id: str) -> int:
        from sqlalchemy import func
        return db.scalar(
            select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id
            )
        ) or 0

    # ────────────────────────────────── Invitation

    @staticmethod
    def create_invitation(db: Session, invitation: Invitation) -> Invitation:
        db.add(invitation)
        db.flush()
        return invitation

    @staticmethod
    def get_invitation_by_token(db: Session, token: str) -> Optional[Invitation]:
        return db.scalar(
            select(Invitation).where(Invitation.token == token)
        )

    @staticmethod
    def get_invitation_by_id(db: Session, inv_id: str) -> Optional[Invitation]:
        return db.scalar(
            select(Invitation).where(Invitation.id == inv_id)
        )

    @staticmethod
    def list_invitations(
        db: Session,
        target_type: str,
        target_id: str,
        *,
        status: str | None = None,
    ) -> list[Invitation]:
        q = select(Invitation).where(
            Invitation.target_type == target_type,
            Invitation.target_id == target_id,
        )
        if status:
            q = q.where(Invitation.status == status)
        return list(db.scalars(q.order_by(Invitation.created_at.desc())))

    @staticmethod
    def list_pending_for_email(db: Session, email: str) -> list[Invitation]:
        return list(
            db.scalars(
                select(Invitation).where(
                    Invitation.invitee_email == email,
                    Invitation.status == "pending",
                ).order_by(Invitation.created_at.desc())
            )
        )

    @staticmethod
    def update_invitation_status(
        db: Session,
        invitation: Invitation,
        status: str,
        *,
        user_id: str | None = None,
    ) -> Invitation:
        invitation.status = status
        if status == "accepted" and user_id:
            invitation.invitee_user_id = user_id
            invitation.accepted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()
        return invitation
