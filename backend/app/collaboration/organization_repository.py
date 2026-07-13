"""Data-access layer for Organization and OrganizationMember tables.

Pure SQL queries — no business logic. The service calls these and applies rules.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.collaboration.models import Organization, OrganizationMember


class OrganizationRepository:

    # ────────────────────────────────── Organization CRUD

    @staticmethod
    def create(db: Session, org: Organization) -> Organization:
        db.add(org)
        db.flush()
        return org

    @staticmethod
    def get_by_id(db: Session, org_id: str) -> Optional[Organization]:
        return db.scalar(
            select(Organization).where(
                Organization.id == org_id,
                Organization.deleted_at.is_(None),
            )
        )

    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Optional[Organization]:
        return db.scalar(
            select(Organization).where(
                Organization.slug == slug,
                Organization.deleted_at.is_(None),
            )
        )

    @staticmethod
    def list_for_user(db: Session, user_id: str) -> list[Organization]:
        """Return all organizations the user is a member of."""
        org_ids_subq = (
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user_id)
            .subquery()
        )
        return list(
            db.scalars(
                select(Organization)
                .where(
                    Organization.id.in_(select(org_ids_subq)),
                    Organization.deleted_at.is_(None),
                )
                .order_by(Organization.name)
            )
        )

    @staticmethod
    def update(db: Session, org: Organization, **fields) -> Organization:
        for k, v in fields.items():
            if v is not None:
                setattr(org, k, v)
        db.flush()
        return org

    @staticmethod
    def soft_delete(db: Session, org: Organization) -> None:
        from datetime import datetime, timezone
        org.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()

    @staticmethod
    def increment_workspace_count(db: Session, org_id: str, delta: int = 1) -> None:
        db.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(workspace_count=Organization.workspace_count + delta)
        )
        db.flush()

    @staticmethod
    def increment_member_count(db: Session, org_id: str, delta: int = 1) -> None:
        db.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(member_count=Organization.member_count + delta)
        )
        db.flush()

    # ────────────────────────────────── OrganizationMember CRUD

    @staticmethod
    def add_member(db: Session, member: OrganizationMember) -> OrganizationMember:
        db.add(member)
        db.flush()
        return member

    @staticmethod
    def get_member(db: Session, org_id: str, user_id: str) -> Optional[OrganizationMember]:
        return db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )

    @staticmethod
    def list_members(db: Session, org_id: str) -> list[OrganizationMember]:
        return list(
            db.scalars(
                select(OrganizationMember)
                .where(OrganizationMember.organization_id == org_id)
                .order_by(OrganizationMember.joined_at)
            )
        )

    @staticmethod
    def remove_member(db: Session, member: OrganizationMember) -> None:
        db.delete(member)
        db.flush()

    @staticmethod
    def update_member_role(db: Session, member: OrganizationMember, role: str) -> OrganizationMember:
        member.role = role
        db.flush()
        return member
