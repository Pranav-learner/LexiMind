"""Pure validation functions for the collaboration module.

No I/O — easy to unit test. Raises ``CollaborationValidationError`` on bad input.
Duplicate-slug detection requires the repository, so it lives in the service.
"""

from __future__ import annotations

import re

from app.collaboration.errors import CollaborationValidationError

ORG_NAME_MIN = 1
ORG_NAME_MAX = 200
ORG_DESC_MAX = 2000
COMMENT_MIN = 1
COMMENT_MAX = 10_000
SLUG_MAX = 200

VALID_ORG_ROLES = frozenset({"owner", "admin", "member"})
VALID_WS_ROLES = frozenset({"owner", "editor", "viewer"})
VALID_INVITATION_TARGETS = frozenset({"organization", "workspace"})
VALID_WORKSPACE_TYPES = frozenset({
    "personal", "shared", "organization", "research", "course", "project",
})

# Role hierarchy (higher number = more privileges).
ROLE_HIERARCHY = {"viewer": 1, "member": 1, "editor": 2, "admin": 3, "owner": 4}

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?$")
_FORBIDDEN_NAME_CHARS = set('/\\<>:"|?*')


def validate_org_name(raw: str) -> str:
    """Return a cleaned organization name or raise."""
    if raw is None:
        raise CollaborationValidationError("Organization name is required.")
    name = " ".join(raw.split())
    if len(name) < ORG_NAME_MIN:
        raise CollaborationValidationError("Organization name cannot be empty.")
    if len(name) > ORG_NAME_MAX:
        raise CollaborationValidationError(
            f"Organization name must be at most {ORG_NAME_MAX} characters."
        )
    bad = _FORBIDDEN_NAME_CHARS.intersection(name)
    if bad:
        raise CollaborationValidationError(
            f"Organization name cannot contain: {' '.join(sorted(bad))}"
        )
    return name


def validate_description(raw: str | None, max_len: int = ORG_DESC_MAX) -> str:
    if raw is None:
        return ""
    text = raw.strip()
    if len(text) > max_len:
        raise CollaborationValidationError(
            f"Description must be at most {max_len} characters."
        )
    return text


def slugify(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
    return slug[:SLUG_MAX] if slug else "org"


def validate_slug(raw: str) -> str:
    """Return a validated slug or raise."""
    slug = raw.strip().lower()[:SLUG_MAX]
    if not slug:
        raise CollaborationValidationError("Slug cannot be empty.")
    if not _SLUG_RE.match(slug):
        raise CollaborationValidationError(
            "Slug must contain only lowercase letters, digits, and hyphens."
        )
    return slug


def validate_role(role: str, *, valid_roles: frozenset) -> str:
    """Return a validated role string or raise."""
    role = role.strip().lower()
    if role not in valid_roles:
        raise CollaborationValidationError(
            f"Invalid role '{role}'. Must be one of: {', '.join(sorted(valid_roles))}."
        )
    return role


def validate_org_role(role: str) -> str:
    return validate_role(role, valid_roles=VALID_ORG_ROLES)


def validate_ws_role(role: str) -> str:
    return validate_role(role, valid_roles=VALID_WS_ROLES)


def validate_comment_content(raw: str) -> str:
    """Return cleaned comment content or raise."""
    if raw is None:
        raise CollaborationValidationError("Comment content is required.")
    text = raw.strip()
    if len(text) < COMMENT_MIN:
        raise CollaborationValidationError("Comment cannot be empty.")
    if len(text) > COMMENT_MAX:
        raise CollaborationValidationError(
            f"Comment must be at most {COMMENT_MAX} characters."
        )
    return text


def validate_invitation_target(target_type: str) -> str:
    target = target_type.strip().lower()
    if target not in VALID_INVITATION_TARGETS:
        raise CollaborationValidationError(
            f"Invalid invitation target '{target}'. Must be 'organization' or 'workspace'."
        )
    return target


def validate_workspace_type(ws_type: str) -> str:
    ws = ws_type.strip().lower()
    if ws not in VALID_WORKSPACE_TYPES:
        raise CollaborationValidationError(
            f"Invalid workspace type '{ws}'. Must be one of: {', '.join(sorted(VALID_WORKSPACE_TYPES))}."
        )
    return ws


def validate_email(email: str) -> str:
    """Basic email validation (not RFC-complete, but catches the common errors)."""
    email = email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise CollaborationValidationError(f"Invalid email address: '{email}'.")
    if len(email) > 320:
        raise CollaborationValidationError("Email address is too long.")
    return email


def role_gte(role: str, min_role: str) -> bool:
    """Check if ``role`` has equal or higher privileges than ``min_role``."""
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(min_role, 0)
