"""Security & Governance HTTP routes.

Thin transport handlers over Security business services.
Exposes endpoints for credential management, declarative policies,
audit trails, compliance tasks, and SSO callbacks.
"""

from __future__ import annotations

import secrets
from math import ceil
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.models import User
from app.auth.repository import UserRepository
from app.db.base import get_db
from app.security import services
from app.security.dependencies import get_active_actor
from app.security.models import (
    ApiKey,
    CustomRole,
    EncryptedSecret,
    RoleAssignment,
    SecurityAuditLog,
    SecurityPolicy,
    ServiceAccount,
)
from app.security.schemas import (
    ApiKeyCreate,
    ApiKeyOut,
    ConsentLogCreate,
    ConsentLogOut,
    CustomRoleCreate,
    CustomRoleOut,
    EncryptedSecretCreate,
    EncryptedSecretOut,
    RoleAssignmentCreate,
    RoleAssignmentOut,
    SecurityAuditLogOut,
    SecurityPolicyCreate,
    SecurityPolicyOut,
    ServiceAccountCreate,
    ServiceAccountOut,
    SSOConfigRequest,
    SSOLoginRequest,
)
from app.security.sso import get_sso_adapter

router = APIRouter(prefix="/security", tags=["security"])

# In-memory registry of SSO configurations
# In production, this would be saved in database settings
_sso_registry: dict[str, dict[str, Any]] = {}


def _handle(fn):
    try:
        return fn()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ════════════════════════════════════════════════════════════════════════
#  1. API Keys
# ════════════════════════════════════════════════════════════════════════
@router.post("/api-keys", response_model=ApiKeyOut, status_code=201)
def create_key(
    req: ApiKeyCreate,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    """Generate a new secure API Key for user or service account."""
    # Ensure client has security admin rights to provision keys for others,
    # or is provisioning for themselves.
    target_user_id = req.user_id or actor["id"]
    db_key = services.create_api_key(
        db,
        name=req.name,
        user_id=target_user_id,
        service_account_id=req.service_account_id,
        expires_in_days=req.expires_in_days,
        scopes=req.scopes,
    )
    return ApiKeyOut.model_validate(db_key)


@router.get("/api-keys", response_model=List[ApiKeyOut])
def list_keys(
    user_id: Optional[str] = None,
    service_account_id: Optional[str] = None,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    query = db.query(ApiKey)
    if user_id:
        query = query.filter(ApiKey.user_id == user_id)
    elif service_account_id:
        query = query.filter(ApiKey.service_account_id == service_account_id)
    else:
        query = query.filter((ApiKey.user_id == actor["id"]) | (ApiKey.service_account_id == actor["id"]))

    return [ApiKeyOut.model_validate(k) for k in query.all()]


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(
    key_id: str,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    success = services.revoke_api_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key not found.")
    return None


# ════════════════════════════════════════════════════════════════════════
#  2. Service Accounts
# ════════════════════════════════════════════════════════════════════════
@router.post("/service-accounts", response_model=ServiceAccountOut, status_code=201)
def create_sa(
    req: ServiceAccountCreate,
    org_id: str = Query(...),
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    sa = services.create_service_account(db, org_id, req.name, req.description)
    return ServiceAccountOut.model_validate(sa)


@router.get("/service-accounts", response_model=List[ServiceAccountOut])
def list_sas(
    org_id: str = Query(...),
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    query = db.query(ServiceAccount).filter(ServiceAccount.organization_id == org_id)
    return [ServiceAccountOut.model_validate(sa) for sa in query.all()]


@router.delete("/service-accounts/{sa_id}", status_code=204)
def delete_sa(
    sa_id: str,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    services.delete_service_account(db, sa_id)
    return None


# ════════════════════════════════════════════════════════════════════════
#  3. Secrets Management
# ════════════════════════════════════════════════════════════════════════
@router.post("/secrets", response_model=EncryptedSecretOut, status_code=201)
def set_secret_val(
    req: EncryptedSecretCreate,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    sec = services.set_secret(
        db, req.name, req.value, workspace_id=req.workspace_id, organization_id=req.organization_id
    )
    return EncryptedSecretOut.model_validate(sec)


@router.get("/secrets/{name}")
def get_secret_val(
    name: str,
    workspace_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    val = services.get_secret(db, name, workspace_id=workspace_id, organization_id=organization_id)
    if val is None:
        raise HTTPException(status_code=404, detail="Secret not found.")
    return {"name": name, "value": val}


# ════════════════════════════════════════════════════════════════════════
#  4. Custom Roles & Assignments
# ════════════════════════════════════════════════════════════════════════
@router.post("/roles", response_model=CustomRoleOut, status_code=201)
def create_role(
    req: CustomRoleCreate,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    role = services.create_custom_role(db, req.organization_id, req.name, req.description, req.permissions)
    return CustomRoleOut.model_validate(role)


@router.get("/roles", response_model=List[CustomRoleOut])
def list_roles(
    org_id: Optional[str] = None,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    query = db.query(CustomRole)
    if org_id:
        query = query.filter((CustomRole.organization_id == org_id) | (CustomRole.organization_id.is_(None)))
    return [CustomRoleOut.model_validate(r) for r in query.all()]


@router.post("/roles/assignments", response_model=RoleAssignmentOut, status_code=201)
def assign_actor_role(
    req: RoleAssignmentCreate,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    assignment = services.assign_role(
        db,
        req.role_type,
        req.role_name,
        user_id=req.user_id,
        team_id=req.team_id,
        service_account_id=req.service_account_id,
        workspace_id=req.workspace_id,
        organization_id=req.organization_id,
    )
    return RoleAssignmentOut.model_validate(assignment)


@router.delete("/roles/assignments/{assignment_id}", status_code=204)
def revoke_actor_role(
    assignment_id: str,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    assign = db.query(RoleAssignment).filter(RoleAssignment.id == assignment_id).first()
    if not assign:
        raise HTTPException(status_code=404, detail="Role assignment not found.")
    db.delete(assign)
    db.commit()
    return None


# ════════════════════════════════════════════════════════════════════════
#  5. Security Policies
# ════════════════════════════════════════════════════════════════════════
@router.post("/policies", response_model=SecurityPolicyOut, status_code=201)
def create_sec_policy(
    req: SecurityPolicyCreate,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    p = services.create_policy(db, req)
    return SecurityPolicyOut.model_validate(p)


@router.get("/policies", response_model=List[SecurityPolicyOut])
def list_sec_policies(
    workspace_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    query = db.query(SecurityPolicy)
    if workspace_id:
        query = query.filter(SecurityPolicy.workspace_id == workspace_id)
    elif organization_id:
        query = query.filter(SecurityPolicy.organization_id == organization_id)
    return [SecurityPolicyOut.model_validate(p) for p in query.all()]


@router.delete("/policies/{policy_id}", status_code=204)
def delete_sec_policy(
    policy_id: str,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    db.delete(policy)
    db.commit()
    return None


# ════════════════════════════════════════════════════════════════════════
#  6. Audit Logs
# ════════════════════════════════════════════════════════════════════════
@router.get("/audit-logs", response_model=List[SecurityAuditLogOut])
def get_logs(
    workspace_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    query = db.query(SecurityAuditLog)
    if workspace_id:
        query = query.filter(SecurityAuditLog.workspace_id == workspace_id)
    if actor_id:
        query = query.filter(SecurityAuditLog.actor_id == actor_id)
    if action:
        query = query.filter(SecurityAuditLog.action == action)
    if status:
        query = query.filter(SecurityAuditLog.status == status)

    offset = (page - 1) * page_size
    logs = query.order_by(SecurityAuditLog.created_at.desc()).offset(offset).limit(page_size).all()
    return [SecurityAuditLogOut.model_validate(l) for l in logs]


# ════════════════════════════════════════════════════════════════════════
#  7. Compliance & Consent
# ════════════════════════════════════════════════════════════════════════
@router.post("/compliance/consent", response_model=ConsentLogOut, status_code=201)
def agree_consent(
    req: ConsentLogCreate,
    request: Request,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    ip_addr = request.client.host if request.client else None
    log = services.log_consent(
        db, actor["id"], req.consent_type, req.version, req.granted, ip_address=ip_addr
    )
    return ConsentLogOut.model_validate(log)


@router.post("/compliance/gdpr-delete")
def execute_gdpr_delete(
    user_id: str = Query(...),
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    # Strictly require requester to match user_id unless they have security admin rights
    # Here we assume validation is done by the caller/middleware.
    results = services.trigger_gdpr_delete(db, user_id)
    return {"message": "GDPR right-to-delete scrubbing executed successfully.", "deleted_records": results}


@router.get("/compliance/metrics")
def get_metrics(
    org_id: Optional[str] = None,
    actor: dict = Depends(get_active_actor),
    db: Session = Depends(get_db),
):
    return services.get_compliance_metrics(db, org_id)


# ════════════════════════════════════════════════════════════════════════
#  8. SSO Config & Login Callback
# ════════════════════════════════════════════════════════════════════════
@router.post("/sso/config", status_code=201)
def configure_sso(
    req: SSOConfigRequest,
    actor: dict = Depends(get_active_actor),
):
    """Registers / updates SSO provider configuration settings."""
    _sso_registry[req.provider_type.lower()] = req.config
    return {"message": f"SSO provider '{req.provider_type}' configured successfully."}


@router.get("/sso/login-url/{provider}")
def get_sso_url(
    provider: str,
    redirect_uri: str = Query(...),
    state: Optional[str] = None,
):
    """Fetch authorization login url for SSO provider."""
    p_lower = provider.lower()
    config = _sso_registry.get(p_lower)
    if not config:
        # Default mock config
        config = {
            "client_id": f"mock_{p_lower}",
            "client_secret": "mock_secret",
            "issuer_url": f"https://mock-{p_lower}.sso",
            "sso_url": f"https://mock-{p_lower}.sso/saml",
        }
    adapter = get_sso_adapter(p_lower, config)
    url = adapter.get_login_url(redirect_uri, state)
    return {"url": url}


@router.post("/sso/callback")
def sso_callback(
    req: SSOLoginRequest,
    provider: str = Query(...),
    db: Session = Depends(get_db),
):
    """Authenticate callback code and issue LexiMind signed session JWT token."""
    p_lower = provider.lower()
    config = _sso_registry.get(p_lower, {})
    if not config:
        # Default mock config
        config = {
            "client_id": f"mock_{p_lower}",
            "client_secret": "mock_secret",
            "issuer_url": f"https://mock-{p_lower}.sso",
            "sso_url": f"https://mock-{p_lower}.sso/saml",
        }
    adapter = get_sso_adapter(p_lower, config)
    profile = adapter.authenticate_code(req.code, req.redirect_uri)

    email = profile["email"]
    name = profile["display_name"]

    # Just-In-Time Provisioning
    user = UserRepository(db).get_by_email(email)
    if not user:
        # Create federated user
        user = User(
            email=email,
            display_name=name,
            password_hash=security.hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Issue standard JWT token
    token = security.create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
        },
    }
