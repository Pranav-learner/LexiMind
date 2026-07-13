"""Phase 9 · Module 1 — Multi-Workspace & Collaboration Platform.

This package transforms LexiMind from a single-user AI operating system into a
collaborative enterprise knowledge platform. It adds:

- **Organizations** — top-level entity grouping workspaces and users.
- **Shared Workspaces** — member-based access to workspaces (owner/editor/viewer).
- **Invitations** — email-based invite system for organizations and workspaces.
- **Comments** — unified commenting on any artifact (document, note, graph, AI, etc.).
- **Activity Feed** — workspace timeline of significant events.
- **Version History** — snapshots of editable artifacts for future diff/restore.
- **Presence** — real-time online status tracking (heartbeat-based TTL).
- **Sync Bus** — long-poll event queue for real-time workspace updates.

Keystone design:
    ``access.resolve_access(user_id, workspace_id, db)`` translates a requesting user
    into the **effective owner_id** for downstream queries. This means ALL existing
    subsystems (Chat, Documents, Knowledge Graph, Agents, etc.) work in shared
    workspaces with ZERO service code changes.

Out-of-scope (deferred to Module 2):
    - RBAC (full permission system)
    - SSO / SAML / OAuth
    - Audit compliance / governance
    - Enterprise deployment (multi-tenant PostgreSQL)
"""
