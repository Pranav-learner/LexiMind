"""Collaboration domain errors (transport-agnostic).

Each carries an HTTP ``status_code`` and a short machine-readable ``code``; the API layer
maps them to HTTP responses so business rules never import FastAPI.

Consistent with ``app.workspaces.errors`` / ``app.chat.errors`` pattern.
"""

from __future__ import annotations


class CollaborationError(Exception):
    status_code = 400
    code = "collaboration_error"


# ──────────────────────────────────────────────────── Organization errors


class OrganizationNotFound(CollaborationError):
    status_code = 404
    code = "organization_not_found"

    def __init__(self, org_id: str):
        super().__init__(f"Organization '{org_id}' was not found.")


class OrganizationNameTaken(CollaborationError):
    status_code = 409
    code = "organization_name_taken"

    def __init__(self, name: str):
        super().__init__(f"An organization named '{name}' already exists.")


class OrganizationSlugTaken(CollaborationError):
    status_code = 409
    code = "organization_slug_taken"

    def __init__(self, slug: str):
        super().__init__(f"The organization slug '{slug}' is already taken.")


# ──────────────────────────────────────────────────── Membership errors


class MembershipError(CollaborationError):
    status_code = 400
    code = "membership_error"


class AlreadyMember(MembershipError):
    status_code = 409
    code = "already_member"

    def __init__(self, context: str = "workspace"):
        super().__init__(f"User is already a member of this {context}.")


class NotAMember(MembershipError):
    status_code = 404
    code = "not_a_member"

    def __init__(self, context: str = "workspace"):
        super().__init__(f"User is not a member of this {context}.")


class CannotRemoveOwner(MembershipError):
    status_code = 400
    code = "cannot_remove_owner"

    def __init__(self):
        super().__init__("Cannot remove the workspace owner. Transfer ownership first.")


class CannotChangeOwnRole(MembershipError):
    status_code = 400
    code = "cannot_change_own_role"

    def __init__(self):
        super().__init__("Cannot change your own role.")


# ──────────────────────────────────────────────────── Access errors


class AccessDenied(CollaborationError):
    status_code = 403
    code = "access_denied"

    def __init__(self, detail: str = "You do not have access to this resource."):
        super().__init__(detail)


class InsufficientRole(CollaborationError):
    status_code = 403
    code = "insufficient_role"

    def __init__(self, required: str, actual: str):
        super().__init__(
            f"This action requires '{required}' role, but you have '{actual}'."
        )


# ──────────────────────────────────────────────────── Invitation errors


class InvitationNotFound(CollaborationError):
    status_code = 404
    code = "invitation_not_found"

    def __init__(self, token_or_id: str = ""):
        super().__init__(f"Invitation not found.")


class InvitationExpired(CollaborationError):
    status_code = 410
    code = "invitation_expired"

    def __init__(self):
        super().__init__("This invitation has expired.")


class InvitationAlreadyAccepted(CollaborationError):
    status_code = 409
    code = "invitation_already_accepted"

    def __init__(self):
        super().__init__("This invitation has already been accepted.")


class InvitationAlreadyProcessed(CollaborationError):
    status_code = 409
    code = "invitation_already_processed"

    def __init__(self, status: str):
        super().__init__(f"This invitation has already been {status}.")


# ──────────────────────────────────────────────────── Comment errors


class CommentNotFound(CollaborationError):
    status_code = 404
    code = "comment_not_found"

    def __init__(self, comment_id: str = ""):
        super().__init__("Comment not found.")


class CommentNotOwned(CollaborationError):
    status_code = 403
    code = "comment_not_owned"

    def __init__(self):
        super().__init__("You can only edit or delete your own comments.")


# ──────────────────────────────────────────────────── Version errors


class VersionNotFound(CollaborationError):
    status_code = 404
    code = "version_not_found"

    def __init__(self, version_id: str = ""):
        super().__init__("Version snapshot not found.")


# ──────────────────────────────────────────────────── Validation errors


class CollaborationValidationError(CollaborationError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str):
        super().__init__(message)
