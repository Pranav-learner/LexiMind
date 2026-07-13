"""Security & Governance API Request/Response Schemas.

Uses Pydantic V2 model validate attributes for ORM serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SecurityBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------- API Keys
class ApiKeyCreate(SecurityBaseModel):
    name: str = Field(..., max_length=120)
    expires_in_days: Optional[int] = Field(None, ge=1)
    scopes: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    service_account_id: Optional[str] = None


class ApiKeyOut(SecurityBaseModel):
    id: str
    prefix: str
    name: str
    scopes: List[str]
    is_active: bool
    expires_at: Optional[datetime] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    # Included only on initial generation response
    raw_key: Optional[str] = None


# ---------------------------------------------------- Service Accounts
class ServiceAccountCreate(SecurityBaseModel):
    name: str = Field(..., max_length=120)
    description: str = Field("", max_length=500)


class ServiceAccountOut(SecurityBaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------- Custom Roles
class CustomRoleCreate(SecurityBaseModel):
    name: str = Field(..., max_length=120)
    description: str = Field("", max_length=500)
    permissions: List[str] = Field(..., min_items=1)
    organization_id: Optional[str] = None


class CustomRoleOut(SecurityBaseModel):
    id: str
    name: str
    description: str
    permissions: List[str]
    organization_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------- Role Assignments
class RoleAssignmentCreate(SecurityBaseModel):
    role_type: str = Field(..., pattern="^(system|custom)$")
    role_name: str = Field(...)  # CustomRole ID or System role name ('admin', 'editor', 'viewer')
    user_id: Optional[str] = None
    team_id: Optional[str] = None
    service_account_id: Optional[str] = None
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None


class RoleAssignmentOut(SecurityBaseModel):
    id: str
    role_type: str
    role_name: str
    user_id: Optional[str] = None
    team_id: Optional[str] = None
    service_account_id: Optional[str] = None
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------- Security Policies
class SecurityPolicyCreate(SecurityBaseModel):
    name: str = Field(..., max_length=120)
    policy_type: str = Field(..., pattern="^(workspace|organization|ai_usage|agent|sharing|retention|export|api)$")
    is_active: bool = True
    rules: Dict[str, Any] = Field(default_factory=dict)
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None


class SecurityPolicyOut(SecurityBaseModel):
    id: str
    name: str
    policy_type: str
    is_active: bool
    rules: Dict[str, Any]
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------- Encrypted Secrets
class EncryptedSecretCreate(SecurityBaseModel):
    name: str = Field(..., max_length=120)
    value: str = Field(..., min_length=1)
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None


class EncryptedSecretOut(SecurityBaseModel):
    id: str
    name: str
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------- Audit Logs
class SecurityAuditLogOut(SecurityBaseModel):
    id: str
    actor_type: str
    actor_id: str
    actor_email: Optional[str] = None
    action: str
    resource_type: str
    resource_id: str
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    ip_address: Optional[str] = None
    status: str
    failure_reason: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------- Compliance & Consent
class ConsentLogCreate(SecurityBaseModel):
    consent_type: str = Field(..., max_length=80)
    version: str = Field(..., max_length=20)
    granted: bool = True


class ConsentLogOut(SecurityBaseModel):
    id: str
    user_id: str
    consent_type: str
    version: str
    granted: bool
    ip_address: Optional[str] = None
    created_at: datetime


class DataRetentionPolicyCreate(SecurityBaseModel):
    resource_type: str = Field(..., max_length=80)
    retention_days: int = Field(..., ge=1)
    is_active: bool = True
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None


class DataRetentionPolicyOut(SecurityBaseModel):
    id: str
    resource_type: str
    retention_days: int
    is_active: bool
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------- SSO & Identity Federation
class SSOConfigRequest(SecurityBaseModel):
    provider_type: str = Field(..., pattern="^(google|okta|entra|keycloak|saml|oidc)$")
    config: Dict[str, Any] = Field(..., description="Configuration dict for SSO provider adapters")


class SSOLoginRequest(SecurityBaseModel):
    code: str = Field(...)
    redirect_uri: str = Field(...)
