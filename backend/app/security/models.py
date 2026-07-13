"""Phase 9 · Module 2 — Security, Governance, and Compliance ORM models.

All tables are additive and created dynamically on startup via ``init_db``.
No Alembic migrations are required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("team"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("teamm"))
    team_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="member", nullable=False)  # 'lead', 'member'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ServiceAccount(Base):
    __tablename__ = "service_accounts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("sa"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("key"))
    user_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    service_account_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    hashed_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)


class CustomRole(Base):
    __tablename__ = "custom_roles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("role"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("ra"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    team_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    service_account_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    role_type: Mapped[str] = mapped_column(String(40), nullable=False)  # 'system', 'custom'
    role_name: Mapped[str] = mapped_column(String(80), nullable=False)  # role id (custom) or name (system)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class SecurityPolicy(Base):
    __tablename__ = "security_policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("policy"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(40), nullable=False)  # 'workspace', 'organization', 'ai_usage', etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("sec"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    iv: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class SecurityAuditLog(Base):
    __tablename__ = "security_audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("audit"))
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)  # 'user', 'service_account', 'system'
    actor_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_email: Mapped[str | None] = mapped_column(String(320), default=None, nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)  # e.g., 'auth.login', 'document.read'
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'success', 'failure'
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    policy_decisions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ConsentLog(Base):
    __tablename__ = "consent_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("consent"))
    user_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    consent_type: Mapped[str] = mapped_column(String(80), nullable=False)  # 'terms_of_service', 'privacy_policy'
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("retention"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)  # 'document', 'chat', 'audit_log', '*'
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)
