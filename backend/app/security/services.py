"""Security, Governance, and Compliance business service layers.

Exposes domain capabilities for managing credentials, keys, encryption keys,
policies, and logs, supporting offline and multi-tenant environments.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import User
from app.collaboration.models import OrganizationMember, WorkspaceMember
from app.security.crypto import decrypt_value, encrypt_value
from app.security.models import (
    ApiKey,
    ConsentLog,
    CustomRole,
    DataRetentionPolicy,
    EncryptedSecret,
    RoleAssignment,
    SecurityAuditLog,
    SecurityPolicy,
    ServiceAccount,
    Team,
    TeamMember,
)
from app.security.schemas import SecurityPolicyCreate
from app.workspaces.models import Workspace


# ---------------------------------------------------- Helper
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------- API Keys
def create_api_key(
    db: Session,
    name: str,
    user_id: str | None = None,
    service_account_id: str | None = None,
    expires_in_days: int | None = None,
    scopes: list[str] | None = None,
) -> ApiKey:
    """Generate a cryptographically secure API key and store its SHA256 hash."""
    entropy = secrets.token_urlsafe(32)
    prefix = "lm_" + secrets.token_hex(4)
    raw_key = f"{prefix}.{entropy}"
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    expires_at = None
    if expires_in_days:
        expires_at = _now() + timedelta(days=expires_in_days)

    db_key = ApiKey(
        user_id=user_id,
        service_account_id=service_account_id,
        hashed_key=hashed_key,
        prefix=prefix,
        name=name,
        scopes=scopes or ["*"],
        expires_at=expires_at,
        is_active=True,
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)

    # Attach raw_key temporarily (not saved to DB) so caller can view it once
    db_key.raw_key = raw_key
    return db_key


def verify_api_key(db: Session, raw_key: str) -> ApiKey | None:
    """Lookup active and non-expired API Key matching the raw key's SHA256 hash."""
    hashed = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key = db.query(ApiKey).filter(ApiKey.hashed_key == hashed, ApiKey.is_active.is_(True)).first()
    if not key:
        return None

    if key.expires_at and key.expires_at < _now():
        return None

    # Track usage frequency
    key.last_used_at = _now()
    db.commit()
    return key


def revoke_api_key(db: Session, key_id: str) -> bool:
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        return False
    key.is_active = False
    db.commit()
    return True


# ---------------------------------------------------- Service Accounts
def create_service_account(db: Session, org_id: str, name: str, description: str = "") -> ServiceAccount:
    sa = ServiceAccount(organization_id=org_id, name=name, description=description, is_active=True)
    db.add(sa)
    db.commit()
    db.refresh(sa)
    return sa


def delete_service_account(db: Session, sa_id: str) -> None:
    sa = db.query(ServiceAccount).filter(ServiceAccount.id == sa_id).first()
    if sa:
        # Revoke all associated API Keys
        db.query(ApiKey).filter(ApiKey.service_account_id == sa_id).update({"is_active": False})
        db.delete(sa)
        db.commit()


# ---------------------------------------------------- Encrypted Secrets
def set_secret(
    db: Session,
    name: str,
    value: str,
    workspace_id: str | None = None,
    organization_id: str | None = None,
) -> EncryptedSecret:
    """Encrypt and store/update a secret key under workspace/org namespaces."""
    enc_val, iv = encrypt_value(value)
    
    existing = db.query(EncryptedSecret).filter(
        EncryptedSecret.name == name,
        EncryptedSecret.workspace_id == workspace_id,
        EncryptedSecret.organization_id == organization_id,
    ).first()

    if existing:
        existing.encrypted_value = enc_val
        existing.iv = iv
        existing.updated_at = _now()
        db.commit()
        db.refresh(existing)
        return existing

    secret = EncryptedSecret(
        workspace_id=workspace_id,
        organization_id=organization_id,
        name=name,
        encrypted_value=enc_val,
        iv=iv,
    )
    db.add(secret)
    db.commit()
    db.refresh(secret)
    return secret


def get_secret(
    db: Session,
    name: str,
    workspace_id: str | None = None,
    organization_id: str | None = None,
) -> str | None:
    """Retrieve and decrypt secret value."""
    secret = db.query(EncryptedSecret).filter(
        EncryptedSecret.name == name,
        EncryptedSecret.workspace_id == workspace_id,
        EncryptedSecret.organization_id == organization_id,
    ).first()

    if not secret:
        return None

    return decrypt_value(secret.encrypted_value, secret.iv)


# ---------------------------------------------------- Custom Roles & Assignments
def create_custom_role(
    db: Session,
    org_id: str | None,
    name: str,
    description: str,
    permissions: list[str],
) -> CustomRole:
    role = CustomRole(
        organization_id=org_id,
        name=name,
        description=description,
        permissions=permissions,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def assign_role(
    db: Session,
    role_type: str,
    role_name: str,
    user_id: str | None = None,
    team_id: str | None = None,
    service_account_id: str | None = None,
    workspace_id: str | None = None,
    organization_id: str | None = None,
) -> RoleAssignment:
    assignment = RoleAssignment(
        role_type=role_type,
        role_name=role_name,
        user_id=user_id,
        team_id=team_id,
        service_account_id=service_account_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


# ---------------------------------------------------- Security Policies
def create_policy(db: Session, req: SecurityPolicyCreate) -> SecurityPolicy:
    policy = SecurityPolicy(
        organization_id=req.organization_id,
        workspace_id=req.workspace_id,
        name=req.name,
        policy_type=req.policy_type,
        is_active=req.is_active,
        rules=req.rules,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


# ---------------------------------------------------- Compliance Logs & Consent
def log_consent(
    db: Session,
    user_id: str,
    consent_type: str,
    version: str,
    granted: bool,
    ip_address: str | None = None,
) -> ConsentLog:
    log = ConsentLog(
        user_id=user_id,
        consent_type=consent_type,
        version=version,
        granted=granted,
        ip_address=ip_address,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def trigger_gdpr_delete(db: Session, user_id: str) -> dict[str, int]:
    """Execute complete right-to-delete / anonymization query across the database."""
    deleted_counts = {}

    # 1. Delete consent records
    c_res = db.query(ConsentLog).filter(ConsentLog.user_id == user_id).delete()
    deleted_counts["consent_logs"] = c_res

    # 2. Revoke API Keys
    ak_res = db.query(ApiKey).filter(ApiKey.user_id == user_id).delete()
    deleted_counts["api_keys"] = ak_res

    # 3. Delete role assignments
    ra_res = db.query(RoleAssignment).filter(RoleAssignment.user_id == user_id).delete()
    deleted_counts["role_assignments"] = ra_res

    # 4. Remove membership mappings
    orgm_res = db.query(OrganizationMember).filter(OrganizationMember.user_id == user_id).delete()
    wsm_res = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete()
    deleted_counts["organization_members"] = orgm_res
    deleted_counts["workspace_members"] = wsm_res

    # 5. Delete Team associations
    tm_res = db.query(TeamMember).filter(TeamMember.user_id == user_id).delete()
    deleted_counts["team_members"] = tm_res

    # 6. Hard delete/Anonymize core User identity row
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        # Re-map email/display to avoid breaking foreign key indices but scrubbing personal data
        user.email = f"anonymized_{secrets.token_hex(8)}@scrubbed.compliance"
        user.display_name = "Anonymized GDPR User"
        user.password_hash = "scrubbed_compliance"
        deleted_counts["users_scrubbed"] = 1
    else:
        deleted_counts["users_scrubbed"] = 0

    db.commit()
    return deleted_counts


def get_compliance_metrics(db: Session, org_id: str | None = None) -> dict[str, Any]:
    """Compile SOC2 / GDPR compliance telemetry stats."""
    total_logs = db.query(SecurityAuditLog).count()
    failed_auths = db.query(SecurityAuditLog).filter(
        SecurityAuditLog.action.startswith("auth."), SecurityAuditLog.status == "failure"
    ).count()

    policy_blocks = db.query(SecurityAuditLog).filter(
        SecurityAuditLog.status == "failure", SecurityAuditLog.failure_reason.like("%policy%")
    ).count()

    consent_accepted = db.query(ConsentLog).filter(ConsentLog.granted.is_(True)).count()
    total_consents = db.query(ConsentLog).count()
    consent_pct = (consent_accepted / total_consents * 100) if total_consents > 0 else 100.0

    return {
        "total_audit_logs": total_logs,
        "failed_authentications": failed_auths,
        "policy_blocks": policy_blocks,
        "consent_acceptance_pct": round(consent_pct, 2),
        "active_keys": db.query(ApiKey).filter(ApiKey.is_active.is_(True)).count(),
        "active_policies": db.query(SecurityPolicy).filter(SecurityPolicy.is_active.is_(True)).count(),
    }


# ---------------------------------------------------- Immutable Audit Log
def log_security_event(
    db: Session,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_email: str | None = None,
    workspace_id: str | None = None,
    organization_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    status: str = "success",
    failure_reason: str | None = None,
    policy_decisions: dict | None = None,
) -> SecurityAuditLog:
    """Save an immutable security audit event log."""
    log = SecurityAuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        failure_reason=failure_reason,
        policy_decisions=policy_decisions or {},
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
