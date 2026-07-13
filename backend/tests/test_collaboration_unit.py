"""Phase 9 · Module 1 — Collaboration unit tests.

Tests the collaboration service layers (OrganizationService, WorkspaceCollaborationService,
CommentService, ActivityService, VersionService, PresenceStore, resolve_access) directly
against the in-memory SQLite database session.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.auth.models import User
from app.workspaces.models import Workspace
from app.collaboration.access import resolve_access, get_user_role, is_member
from app.collaboration.errors import (
    AccessDenied,
    AlreadyMember,
    CannotRemoveOwner,
    CollaborationValidationError,
    InsufficientRole,
    InvitationAlreadyProcessed,
    InvitationExpired,
    InvitationNotFound,
    NotAMember,
    OrganizationSlugTaken,
)
from app.collaboration.organization_service import OrganizationService
from app.collaboration.workspace_collaboration_service import WorkspaceCollaborationService
from app.collaboration.comment_service import CommentService
from app.collaboration.activity_service import ActivityService
from app.collaboration.version_service import VersionService
from app.collaboration.presence import presence_store, PresenceStore
from app.collaboration.validation import slugify, validate_org_name, validate_email


@pytest.fixture
def users(db_session: Session) -> tuple[User, User, User]:
    """Create three test users: Alice, Bob, Charlie."""
    alice = User(id="usr_alice", email="alice@example.com", display_name="Alice", password_hash="pw")
    bob = User(id="usr_bob", email="bob@example.com", display_name="Bob", password_hash="pw")
    charlie = User(id="usr_charlie", email="charlie@example.com", display_name="Charlie", password_hash="pw")
    db_session.add_all([alice, bob, charlie])
    db_session.commit()
    return alice, bob, charlie


@pytest.fixture
def workspace_alice(db_session: Session, users) -> Workspace:
    """Create a workspace owned by Alice."""
    alice, _, _ = users
    ws = Workspace(id="ws_alice", name="Alice Workspace", owner_id=alice.id)
    db_session.add(ws)
    db_session.commit()
    return ws


# ════════════════════════════════════════════════════════════════════════
#  1. resolve_access unit tests
# ════════════════════════════════════════════════════════════════════════


def test_resolve_access_owner(db_session: Session, users, workspace_alice):
    alice, _, _ = users
    # Owner should resolve successfully and return their own ID.
    effective_owner = resolve_access(alice.id, workspace_alice.id, db_session)
    assert effective_owner == alice.id


def test_resolve_access_non_member_denied(db_session: Session, users, workspace_alice):
    _, bob, _ = users
    # Non-member should raise AccessDenied.
    with pytest.raises(AccessDenied):
        resolve_access(bob.id, workspace_alice.id, db_session)


def test_resolve_access_member(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    wcs = WorkspaceCollaborationService()

    # Add Bob as a viewer.
    wcs.add_member(db_session, workspace_alice.id, user_id=bob.id, role="viewer")

    # Member should resolve successfully to the workspace owner (Alice).
    effective_owner = resolve_access(bob.id, workspace_alice.id, db_session)
    assert effective_owner == alice.id


def test_resolve_access_role_check(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    wcs = WorkspaceCollaborationService()

    # Add Bob as a viewer.
    wcs.add_member(db_session, workspace_alice.id, user_id=bob.id, role="viewer")

    # Viewer accessing with min_role viewer -> OK.
    assert resolve_access(bob.id, workspace_alice.id, db_session, min_role="viewer") == alice.id

    # Viewer accessing with min_role editor -> raises InsufficientRole.
    with pytest.raises(InsufficientRole):
        resolve_access(bob.id, workspace_alice.id, db_session, min_role="editor")


# ════════════════════════════════════════════════════════════════════════
#  2. Organization unit tests
# ════════════════════════════════════════════════════════════════════════


def test_organization_crud(db_session: Session, users):
    alice, bob, _ = users
    org_svc = OrganizationService()

    # Create.
    org = org_svc.create(db_session, creator_id=alice.id, name="Acme Corp", description="Acme stuff")
    assert org.id.startswith("org_")
    assert org.name == "Acme Corp"
    assert org.slug == "acme-corp"
    assert org.creator_id == alice.id

    # Duplicate slug.
    with pytest.raises(OrganizationSlugTaken):
        org_svc.create(db_session, creator_id=bob.id, name="Acme Corp")

    # Read.
    fetched = org_svc.get(db_session, org.id)
    assert fetched.name == "Acme Corp"

    # List.
    list_orgs = org_svc.list_for_user(db_session, alice.id)
    assert len(list_orgs) == 1
    assert list_orgs[0].id == org.id

    # Update.
    updated = org_svc.update(db_session, org.id, name="Acme International", description="New description")
    assert updated.name == "Acme International"
    assert updated.description == "New description"

    # Delete (non-owner denied).
    with pytest.raises(CollaborationValidationError):
        org_svc.delete(db_session, org.id, actor_id=bob.id)

    # Delete (owner OK).
    org_svc.delete(db_session, org.id, actor_id=alice.id)
    with pytest.raises(Exception):  # OrganizationNotFound
        org_svc.get(db_session, org.id)


def test_organization_membership(db_session: Session, users):
    alice, bob, charlie = users
    org_svc = OrganizationService()
    org = org_svc.create(db_session, creator_id=alice.id, name="Stark Industries")

    # Add member.
    m = org_svc.add_member(db_session, org.id, user_id=bob.id, role="admin")
    assert m.user_id == bob.id
    assert m.role == "admin"

    # Duplicate member.
    with pytest.raises(AlreadyMember):
        org_svc.add_member(db_session, org.id, user_id=bob.id)

    # List members.
    members = org_svc.list_members(db_session, org.id)
    assert len(members) == 2  # Alice (owner), Bob (admin)

    # Change role.
    org_svc.change_member_role(db_session, org.id, bob.id, "member")
    m_updated = org_svc.repo.get_member(db_session, org.id, bob.id)
    assert m_updated.role == "member"

    # Remove member.
    org_svc.remove_member(db_session, org.id, bob.id)
    assert org_svc.repo.get_member(db_session, org.id, bob.id) is None


# ════════════════════════════════════════════════════════════════════════
#  3. Invitation lifecycle unit tests
# ════════════════════════════════════════════════════════════════════════


def test_invitation_lifecycle(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    wcs = WorkspaceCollaborationService()

    # Invite Bob.
    inv = wcs.invite(
        db_session, target_type="workspace", target_id=workspace_alice.id,
        inviter_id=alice.id, email=bob.email, role="editor",
    )
    assert inv.token is not None
    assert inv.status == "pending"

    # Accept.
    accepted_inv = wcs.accept_invitation(db_session, inv.token, user_id=bob.id)
    assert accepted_inv.status == "accepted"
    assert accepted_inv.invitee_user_id == bob.id

    # Verify Bob is now a member of the workspace.
    assert is_member(bob.id, workspace_alice.id, db_session)
    assert get_user_role(bob.id, workspace_alice.id, db_session) == "editor"

    # Already accepted.
    with pytest.raises(InvitationAlreadyProcessed):
        wcs.accept_invitation(db_session, inv.token, user_id=bob.id)


def test_invitation_decline(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    wcs = WorkspaceCollaborationService()

    inv = wcs.invite(
        db_session, target_type="workspace", target_id=workspace_alice.id,
        inviter_id=alice.id, email=bob.email, role="editor",
    )

    # Decline.
    declined = wcs.decline_invitation(db_session, inv.token)
    assert declined.status == "declined"


def test_invitation_expiration(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    wcs = WorkspaceCollaborationService()

    inv = wcs.invite(
        db_session, target_type="workspace", target_id=workspace_alice.id,
        inviter_id=alice.id, email=bob.email, role="editor",
    )

    # Artificially expire the invitation.
    inv.expires_at = datetime(2020, 1, 1)
    db_session.commit()

    # Accept should fail.
    with pytest.raises(InvitationExpired):
        wcs.accept_invitation(db_session, inv.token, user_id=bob.id)


# ════════════════════════════════════════════════════════════════════════
#  4. Comment unit tests
# ════════════════════════════════════════════════════════════════════════


def test_comment_operations(db_session: Session, users, workspace_alice):
    alice, bob, _ = users
    cmt_svc = CommentService()

    # Create comment.
    c1 = cmt_svc.create(
        db_session, workspace_id=workspace_alice.id, author_id=alice.id,
        target_type="document", target_id="doc_1", content="Interesting document.",
    )
    assert c1.id.startswith("cmt_")
    assert c1.content == "Interesting document."

    # Threaded reply.
    reply = cmt_svc.create(
        db_session, workspace_id=workspace_alice.id, author_id=bob.id,
        target_type="document", target_id="doc_1", content="Agreed.",
        parent_comment_id=c1.id,
    )
    assert reply.parent_comment_id == c1.id

    # List comments.
    comments = cmt_svc.list_for_target(db_session, workspace_alice.id, "document", "doc_1")
    assert len(comments) == 2

    # Edit.
    edited = cmt_svc.edit(db_session, c1.id, actor_id=alice.id, content="Updated text.")
    assert edited.content == "Updated text."
    assert edited.is_edited

    # Edit other's comment -> denied.
    with pytest.raises(Exception):
        cmt_svc.edit(db_session, c1.id, actor_id=bob.id, content="Hack.")

    # Resolve comment.
    resolved = cmt_svc.resolve(db_session, c1.id, resolver_id=bob.id)
    assert resolved.is_resolved
    assert resolved.resolved_by == bob.id

    # Delete.
    cmt_svc.delete(db_session, reply.id, actor_id=bob.id)
    assert len(cmt_svc.repo.list_replies(db_session, c1.id)) == 0


# ════════════════════════════════════════════════════════════════════════
#  5. Activity feed unit tests
# ════════════════════════════════════════════════════════════════════════


def test_activity_feed(db_session: Session, users, workspace_alice):
    alice, _, _ = users
    act_svc = ActivityService()

    # Record event.
    e = act_svc.record(
        db_session, workspace_id=workspace_alice.id, actor_id=alice.id,
        event_type="document_uploaded", description="Uploaded thesis.pdf",
        target_type="document", target_id="doc_123", target_title="thesis.pdf",
    )
    assert e.id.startswith("act_")
    assert e.event_type == "document_uploaded"

    # List.
    events = act_svc.list_for_workspace(db_session, workspace_alice.id)
    assert len(events) == 1
    assert events[0].id == e.id
    assert events[0].description == "Uploaded thesis.pdf"


# ════════════════════════════════════════════════════════════════════════
#  6. Version history unit tests
# ════════════════════════════════════════════════════════════════════════


def test_version_history(db_session: Session, users, workspace_alice):
    alice, _, _ = users
    ver_svc = VersionService()

    # First version.
    v1 = ver_svc.snapshot(
        db_session, workspace_id=workspace_alice.id, actor_id=alice.id,
        target_type="note", target_id="note_1", snapshot={"title": "Version 1", "body": "Hello"},
        change_summary="Initial save",
    )
    assert v1.version_number == 1

    # Second version.
    v2 = ver_svc.snapshot(
        db_session, workspace_id=workspace_alice.id, actor_id=alice.id,
        target_type="note", target_id="note_1", snapshot={"title": "Version 2", "body": "World"},
        change_summary="Updated body",
    )
    assert v2.version_number == 2

    # Fetch.
    fetched = ver_svc.get(db_session, v2.id)
    assert fetched.snapshot == {"title": "Version 2", "body": "World"}

    # List.
    versions = ver_svc.list_for_target(db_session, "note", "note_1")
    assert len(versions) == 2
    assert versions[0].version_number == 2
    assert versions[1].version_number == 1


# ════════════════════════════════════════════════════════════════════════
#  7. Presence Store unit tests
# ════════════════════════════════════════════════════════════════════════


def test_presence_store():
    # Use a local PresenceStore instance to avoid modifying the global singleton.
    store = PresenceStore(ttl_seconds=1)

    # Alice online.
    store.heartbeat(
        workspace_id="ws_1", user_id="usr_alice", display_name="Alice",
        active_document_id="doc_x", active_artifact_type="document", active_artifact_id="doc_x",
    )

    online = store.get_online("ws_1")
    assert len(online) == 1
    assert online[0]["user_id"] == "usr_alice"
    assert online[0]["active_document_id"] == "doc_x"

    # Wait for TTL to expire presence.
    time.sleep(1.1)
    assert len(store.get_online("ws_1")) == 0


# ════════════════════════════════════════════════════════════════════════
#  8. Pure validation unit tests
# ════════════════════════════════════════════════════════════════════════


def test_pure_validation():
    # Slugify.
    assert slugify("Acme Corp!!!") == "acme-corp"
    assert slugify("   STARK    industries   ") == "stark-industries"

    # Org name.
    assert validate_org_name("Stark Enterprises") == "Stark Enterprises"
    with pytest.raises(CollaborationValidationError):
        validate_org_name("")
    with pytest.raises(CollaborationValidationError):
        validate_org_name("a" * 300)
    with pytest.raises(CollaborationValidationError):
        validate_org_name("Bad/Name")

    # Email.
    assert validate_email("alice@stark.com") == "alice@stark.com"
    with pytest.raises(CollaborationValidationError):
        validate_email("bad-email")
