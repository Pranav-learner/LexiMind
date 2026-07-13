"""Organization CRUD + member management business logic.

Orchestrates validation, repository calls, and domain-error semantics. Never imports
FastAPI — transport-agnostic, testable with a plain SQLAlchemy session.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.collaboration.errors import (
    AlreadyMember,
    CannotRemoveOwner,
    CollaborationValidationError,
    NotAMember,
    OrganizationNameTaken,
    OrganizationNotFound,
    OrganizationSlugTaken,
)
from app.collaboration.models import Organization, OrganizationMember
from app.collaboration.organization_repository import OrganizationRepository
from app.collaboration.validation import (
    slugify,
    validate_description,
    validate_org_name,
    validate_org_role,
    validate_slug,
)


class OrganizationService:

    def __init__(self, repo: OrganizationRepository | None = None):
        self.repo = repo or OrganizationRepository()

    # ────────────────────────────────── Create

    def create(
        self,
        db: Session,
        *,
        creator_id: str,
        name: str,
        description: str = "",
        icon: str = "🏢",
        color: str = "#6366f1",
        slug: str | None = None,
    ) -> Organization:
        name = validate_org_name(name)
        description = validate_description(description)
        slug = validate_slug(slug) if slug else slugify(name)

        # Check slug uniqueness.
        existing = self.repo.get_by_slug(db, slug)
        if existing:
            raise OrganizationSlugTaken(slug)

        org = Organization(
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            color=color,
            creator_id=creator_id,
        )
        self.repo.create(db, org)

        # Auto-add the creator as owner.
        member = OrganizationMember(
            organization_id=org.id,
            user_id=creator_id,
            role="owner",
        )
        self.repo.add_member(db, member)

        db.commit()
        return org

    # ────────────────────────────────── Read

    def get(self, db: Session, org_id: str) -> Organization:
        org = self.repo.get_by_id(db, org_id)
        if org is None:
            raise OrganizationNotFound(org_id)
        return org

    def list_for_user(self, db: Session, user_id: str) -> list[Organization]:
        return self.repo.list_for_user(db, user_id)

    # ────────────────────────────────── Update

    def update(
        self,
        db: Session,
        org_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
    ) -> Organization:
        org = self.get(db, org_id)

        if name is not None:
            name = validate_org_name(name)
        if description is not None:
            description = validate_description(description)

        self.repo.update(db, org, name=name, description=description, icon=icon, color=color)
        db.commit()
        return org

    # ────────────────────────────────── Delete

    def delete(self, db: Session, org_id: str, *, actor_id: str) -> None:
        org = self.get(db, org_id)
        # Only the creator / owner can delete.
        if org.creator_id != actor_id:
            member = self.repo.get_member(db, org_id, actor_id)
            if member is None or member.role != "owner":
                raise CollaborationValidationError(
                    "Only the organization owner can delete it."
                )
        self.repo.soft_delete(db, org)
        db.commit()

    # ────────────────────────────────── Members

    def add_member(
        self,
        db: Session,
        org_id: str,
        *,
        user_id: str,
        role: str = "member",
    ) -> OrganizationMember:
        self.get(db, org_id)  # ensure org exists
        role = validate_org_role(role)

        existing = self.repo.get_member(db, org_id, user_id)
        if existing:
            raise AlreadyMember("organization")

        member = OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=role,
        )
        self.repo.add_member(db, member)
        self.repo.increment_member_count(db, org_id)
        db.commit()
        return member

    def remove_member(
        self,
        db: Session,
        org_id: str,
        user_id: str,
    ) -> None:
        org = self.get(db, org_id)
        member = self.repo.get_member(db, org_id, user_id)
        if member is None:
            raise NotAMember("organization")
        if member.role == "owner":
            raise CannotRemoveOwner()
        self.repo.remove_member(db, member)
        self.repo.increment_member_count(db, org_id, -1)
        db.commit()

    def change_member_role(
        self,
        db: Session,
        org_id: str,
        user_id: str,
        new_role: str,
    ) -> OrganizationMember:
        self.get(db, org_id)
        new_role = validate_org_role(new_role)
        member = self.repo.get_member(db, org_id, user_id)
        if member is None:
            raise NotAMember("organization")
        self.repo.update_member_role(db, member, new_role)
        db.commit()
        return member

    def list_members(self, db: Session, org_id: str) -> list[OrganizationMember]:
        self.get(db, org_id)  # ensure org exists
        return self.repo.list_members(db, org_id)
